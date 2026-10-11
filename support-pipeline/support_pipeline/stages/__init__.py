"""Pipeline stages. Each module exposes ``run(ctx)``."""
from . import classify, draft, finalise, load, preprocess, priority, retrieve, route, validate

STAGE_FUNCS = {
    "load": load.run,
    "preprocess": preprocess.run,
    "classify": classify.run,
    "retrieve": retrieve.run,
    "priority": priority.run,
    "route": route.run,
    "draft": draft.run,
    "validate": validate.run,
    "finalise": finalise.run,
}
