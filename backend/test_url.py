import urllib.parse
params = {
    "client_id": "11007582879617.10995924141202",
    "scope": "",
    "user_scope": "chat:write channels:read im:write",
    "redirect_uri": "https://flux.trigtbh.dev/auth/slack/callback",
    "state": "akshai"
}
print("https://slack.com/oauth/v2/authorize?" + urllib.parse.urlencode(params))
