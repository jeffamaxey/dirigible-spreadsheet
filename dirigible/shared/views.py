# Copyright (c) 2010 Resolver Systems Ltd, PythonAnywhere LLP
# See LICENSE.md
#

from django.http import HttpResponsePermanentRedirect


# Our redirect_to supports query string parameters, which
# the normal Django generic one (irritatingly) does not.
def redirect_to(request, url):
    if query_string := request.META.get("QUERY_STRING"):
        url = f"{url}?{query_string}"
    return HttpResponsePermanentRedirect(url)
