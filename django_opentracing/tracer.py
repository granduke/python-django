from django.conf import settings
import opentracing

try:
    from threading import local
except ImportError:
    from django.utils._threading_local import local
_thread_locals = local()

django_tracer = None

def get_tracer():
    return opentracing.tracer

def get_current_span(request=None):
    if request is None:
        request = getattr(_thread_locals, "request", None)
    # this lets django rest framework work seamlessly since they wrap the request
    if hasattr(request, '_request'):
        request = request._request
    if django_tracer != None:
        return django_tracer.get_span(request)
    else:
        return None


class DjangoTracer(object):
    '''
    @param tracer the OpenTracing tracer to be used
    to trace requests using this DjangoTracer
    '''
    def __init__(self, tracer):
        global django_tracer
        django_tracer = self
        self._tracer = tracer
        self._current_spans = {}
        if not hasattr(settings, 'OPENTRACING_TRACE_ALL'):
            self._trace_all = False
        elif not getattr(settings, 'OPENTRACING_TRACE_ALL'):
            self._trace_all = False
        else:
            self._trace_all = True

    def get_span(self, request):
        '''
        @param request
        Returns the span tracing this request
        '''
        return self._current_spans.get(request, None)

    def trace(self, *attributes):
        '''
        Function decorator that traces functions
        NOTE: Must be placed after the @app.route decorator
        @param attributes any number of flask.Request attributes
        (strings) to be set as tags on the created span
        '''
        def decorator(view_func):
            # TODO: do we want to provide option of overriding trace_all_requests so that they
            # can trace certain attributes of the request for just this request (this would require
            # to reinstate the name-mangling with a trace identifier, and another settings key)
            if self._trace_all:
                return view_func
            # otherwise, execute decorator
            def wrapper(request):
                span = self._apply_tracing(request, view_func, list(attributes))
                r = view_func(request)
                self._finish_tracing(request)
                return r
            return wrapper
        return decorator

    def _apply_tracing(self, request, view_func, attributes):
        '''
        Helper function to avoid rewriting for middleware and decorator.
        Returns a new span from the request with logged attributes and
        correct operation name from the view_func.
        '''
        setattr(_thread_locals, 'request', request)
        # strip headers for trace info
        headers = {}
        for k,v in request.META.items():
            k = k.lower().replace('_','-')
            if k.startswith('http-'):
                k = k[5:]
            headers[k] = v

        # start new span from trace info
        span = None
        operation_name = view_func.__name__
        try:
            span_ctx = self._tracer.extract(opentracing.Format.HTTP_HEADERS, headers)
            span = self._tracer.start_span(operation_name=operation_name, child_of=span_ctx)
        except (opentracing.InvalidCarrierException, opentracing.SpanContextCorruptedException) as e:
            span = self._tracer.start_span(operation_name=operation_name)
        if span is None:
            span = self._tracer.start_span(operation_name=operation_name)

        # add span to current spans
        self._current_spans[request] = span

        # log any traced attributes
        for attr in attributes:
            if hasattr(request, attr):
                payload = str(getattr(request, attr))
                if payload:
                    span.set_tag(attr, payload)
        return span

    def _finish_tracing(self, request):
        span = self._current_spans.pop(request, None)
        if span is not None:
            span.finish()
        setattr(_thread_locals, 'request', None)
