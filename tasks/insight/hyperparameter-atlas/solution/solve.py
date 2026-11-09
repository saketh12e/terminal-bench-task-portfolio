"""Recompute local training certificates and the complete coupled feedback graph."""

import json
import os
from pathlib import Path
from training import problems
from regions import enumerate_regions
from feedback import equilibria, select, responses
from curriculum import solve_curriculum


def main():
    app = Path(os.environ.get("ATLAS_APP", "/app"))
    data = json.loads((app / "demand.json").read_text())
    models = problems(data)
    atlases = {name: enumerate_regions(p) for name, p in models.items()}
    sheets = equilibria(data, models, atlases)
    for filename, artifact in [
        ("atlas.json", dict(version=2, fits=atlases)),
        ("equilibria.json", dict(version=2, cells=sheets)),
        ("selection.json", select(models, sheets)),
        ("sensitivities.json", responses(data, models, sheets)),
        ("curriculum.json", solve_curriculum(data, models, sheets)),
    ]:
        (app / filename).write_text(
            json.dumps(artifact, separators=(",", ":"), allow_nan=False) + "\n"
        )


if __name__ == "__main__":
    main()
