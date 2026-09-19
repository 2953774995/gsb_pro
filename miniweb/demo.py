"""Default routes used by the miniweb command-line launcher."""

import json

from .application import Application
from .response import redirect
from .router import Router


def create_demo_app(static_root=None) -> Application:
    router = Router()

    # When a static root is provided, let it own "/" and serve index.html.
    if static_root is None:

        @router.get("/")
        def index(request):
            return (
                200,
                {"Content-Type": "text/html; charset=utf-8"},
                """<!doctype html><html><head><meta charset='utf-8'><title>miniweb</title></head>
<body><h1>miniweb is running</h1>
<ul><li><a href='/hello?name=world'>route with query</a></li>
<li><a href='/users/42'>path parameter</a></li>
<li><a href='/redirect'>302 redirect</a></li></ul>
</body></html>""",
            )

    @router.get("/hello")
    def hello(request):
        name = request.query.get("name", "miniweb")
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, f"hello {name}"

    @router.get("/users/:id")
    def user(request):
        user_id = request.params["id"]
        return (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"id": user_id}, separators=(",", ":")) + "\n",
        )

    @router.post("/echo/form")
    def echo_form(request):
        pairs = "&".join(f"{k}={v}" for k, v in sorted(request.form.items()))
        return 200, {"Content-Type": "text/plain; charset=utf-8"}, pairs

    @router.post("/echo/json")
    def echo_json(request):
        # Accessing request.json turns malformed JSON into a 400 response.
        return 200, {"Content-Type": "application/json"}, request.json

    @router.get("/old")
    def old_route(request):
        return redirect("/hello", status=301)

    @router.get("/redirect")
    def do_redirect(request):
        return redirect("/hello", status=302)

    @router.get("/boom")
    def boom(request):
        raise RuntimeError("this exception is converted to a safe 500 page")

    return Application(router=router, static_root=static_root)
