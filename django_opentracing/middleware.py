from importlib import import_module
import django
from django.conf import settings
import opentracing
from .tracer import DjangoTracer

try:
    # Django >= 1.10
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    # Not required for Django <= 1.9, see:
    # https://docs.djangoproject.com/en/1.10/topics/http/middleware/#upgrading-pre-django-1-10-style-middleware
    MiddlewareMixin = object

class OpenTracingMiddleware(MiddlewareMixin):
    '''
    In Django <= 1.9 __init__() is only called once, no arguments, when the Web server responds to the first request
    '''
    def __init__(self, get_response=None, *args, **kwargs):
        self._tracer = None
        self.get_response = get_response

        # in django 1.10, __init__ is called on server startup
        if int(django.get_version().split('.')[1]) <= 9:
            if self._tracer == None:
                self._tracer = self.init_tracer()

        super(OpenTracingMiddleware, self).__init__(*args, **kwargs)

    def __call__(self, request):
        if self._tracer == None:
            self._tracer = self.init_tracer()

        return self.get_response(request)

    def init_tracer(self):
        tracer_type = getattr(settings, 'OPENTRACING_TRACER', opentracing.Tracer)
        if isinstance(tracer_type, str):
            tracer_type = import_module(tracer_type)
        tracer = tracer_type()
        return DjangoTracer(tracer)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if self._tracer == None:
            self._tracer = self.init_tracer()

        if hasattr(settings, 'OPENTRACING_TRACED_ATTRIBUTES'):
            traced_attributes = getattr(settings, 'OPENTRACING_TRACED_ATTRIBUTES')
        else:
            traced_attributes = []
        self._tracer._apply_tracing(request, view_func, traced_attributes)

    def process_response(self, request, response):
        self._tracer._finish_tracing(request)
        return response

