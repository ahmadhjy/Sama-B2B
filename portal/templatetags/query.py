from django import template
register=template.Library()

@register.simple_tag(takes_context=True)
def query_url(context, **changes):
    params=context['request'].GET.copy()
    for key,value in changes.items():
        if value is None: params.pop(key,None)
        else: params[key]=str(value)
    return '?'+params.urlencode()
