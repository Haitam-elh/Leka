"""Every API route with its tag and the permissions its dependencies require
(LEKA-453): the paths from the app's OpenAPI schema, the permissions read off
each route's `require_permission` dependencies.

    cd api && .venv/bin/python ../docs/product/export_api_routes.py > ../docs/product/ux-migration-api-routes.tsv
"""

from fastapi.routing import APIRoute

from leka.api import api_router
from leka.main import app


def permissions(dependant):
    found = set()
    for cell in getattr(dependant.call, "__closure__", None) or ():
        try:
            value = cell.cell_contents
        except ValueError:
            continue
        if type(value).__name__ == "Permission":
            found.add(value.value)
    for nested in dependant.dependencies:
        found |= permissions(nested)
    return found


by_name = {}


def walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                by_name.setdefault((route.name, method), set()).update(permissions(route.dependant))
        elif hasattr(route, "original_router"):
            walk(route.original_router.routes)


walk(api_router.routes)
for path, operations in app.openapi()["paths"].items():
    for method, operation in operations.items():
        operation_id = operation.get("operationId", "")
        names = sorted(
            (n for n, m in by_name if m == method.upper() and operation_id.startswith(n + "_")),
            key=len,
            reverse=True,
        )
        required = by_name[(names[0], method.upper())] if names else set()
        print(
            "\t".join(
                [
                    method.upper(),
                    path,
                    ",".join(operation.get("tags", [])) or "-",
                    ",".join(sorted(required)) or "-",
                    (operation.get("summary") or operation_id).replace("\t", " "),
                ]
            )
        )
