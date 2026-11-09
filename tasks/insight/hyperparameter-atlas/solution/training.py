"""Reference training transformations and hierarchical least-squares objectives."""

import numpy as np


def problems(data):
    rows = {r["id"]: r for r in data["rows"]}
    result = {}
    for name, split in data["fits"].items():
        train = [rows[i] for i in split["train"]]
        x = np.array([r["x"] for r in train], float)
        weight = np.array([r["weight"] for r in train], float)
        weight /= weight.sum()
        mu = weight @ x
        scale = np.sqrt(weight @ ((x - mu) ** 2) + data["scale_floor"] ** 2)

        def design(ids):
            rs = [rows[i] for i in ids]
            if not rs:
                return np.zeros((0, 6))
            xx = (np.array([r["x"] for r in rs]) - mu) / scale
            return np.column_stack(
                [
                    xx,
                    [r["head"] == 0 for r in rs],
                    [r["head"] == 1 for r in rs],
                    np.ones(len(rs)),
                ]
            )

        Z = design(split["train"])
        y = np.array([r["y"] for r in train])
        teacher = np.array([r["teacher"] for r in train])
        T = np.eye(6)
        T[:3, :3] = np.diag(1 / scale)
        T[5, :3] = -mu / scale
        out = dict(
            H=Z.T @ (weight[:, None] * Z) + np.diag(data["ridge"]),
            g0=-Z.T @ (weight * y),
            g1=-Z.T @ (weight * (teacher - y)),
            A=np.array([r["normal"] for r in data["raw_inequalities"]]) @ T,
            b0=np.array([r["offset"] for r in data["raw_inequalities"]]),
            b1=np.array([r["relax"] for r in data["raw_inequalities"]]),
            E=np.array([[0.0, 0, 0, 1, 1, 0]]),
            T=T,
            mu=mu,
            scale=scale,
        )
        val = [rows[i] for i in split["validation"]]
        out["Zv"] = design(split["validation"])
        out["yv"] = np.array([r["y"] for r in val])
        vv = np.array([r["weight"] for r in val], float)
        out["vv"] = vv / vv.sum() if len(vv) else vv
        C0 = np.array(
            [weight * np.array([r["head"] == h for r in train]) for h in (0, 1)]
        )
        C0 /= C0.sum(axis=1)[:, None]
        C1 = np.array([weight * Z[:, 0], weight * Z[:, 1]])
        B = [C0 @ Z, C1 @ Z]
        stages = []
        prior = out["E"]
        for C, design in zip((C0, C1), B):
            stages.append(
                dict(
                    H=design.T @ design,
                    g0=-design.T @ C @ y,
                    g1=-design.T @ C @ (teacher - y),
                    F=prior.copy(),
                )
            )
            prior = np.vstack([prior, design])
        stages.append(dict(H=out["H"], g0=out["g0"], g1=out["g1"], F=prior))
        out["stages"] = stages
        out["priority_designs"] = B
        result[name] = out
    return result
