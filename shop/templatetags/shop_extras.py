from django import template
import re

register = template.Library()

@register.filter
def slugify(value):
    s = str(value).lower().strip()
    s = re.sub(r'[^\w\s-]', '', s)
    s = re.sub(r'[\s_]+', '-', s)
    s = re.sub(r'-+', '-', s)
    return s

@register.filter
def get_item(dict_obj, key):
    return dict_obj.get(key, '')

@register.simple_tag
def site_rating_info():
    from shop.models import SiteRating
    ratings = SiteRating.objects.all()
    avg = round(sum(r.rating for r in ratings) / len(ratings), 1) if ratings else 0
    return {'avg': avg, 'count': len(ratings)}

@register.filter
def urlencode(value):
    import urllib.parse
    return urllib.parse.quote(str(value))
