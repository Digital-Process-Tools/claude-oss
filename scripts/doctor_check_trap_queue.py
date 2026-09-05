"""``check_trap_queue`` -- one check, in its own module per the #497/#630 convention.

Every shared name -- `report`, and `trap_curate` itself -- is reached through `doctor`
imported as a module rather than `from doctor import name`, so a test's
`monkeypatch.setattr(doctor, ...)` still reaches this code after the move.
"""

import doctor

try:
    import trap_curate
except ImportError:  # pragma: no cover - the module sits beside this file
    trap_curate = None


def check_trap_queue(project_dir):
    """#905: how many traps are waiting for `/oss:curate`, in the three states.

    Reported, never blocking. A gate on this queue would refuse a security fix over a typo
    somebody logged on Friday, and the ranking table already says a blocking-class finding
    releases immediately -- so the forcing function here is visibility, and this line is it.

    `none` is an OK and not a silence: a cycle that curated everything and a cycle nobody
    logged in look the same from outside, and saying `none waiting` is what separates them
    from `could-not-read`, which is the state this whole repository exists to keep nameable.
    """
    if trap_curate is None:
        doctor.report(
            "WARN",
            "trap queue: not checked (scripts/trap_curate.py could not be imported)",
        )
        return
    result = trap_curate.waiting(project_dir)
    if result["state"] == "could-not-read":
        doctor.report(
            "WARN",
            "trap queue: could not be read -- {}. UNKNOWN, not zero: nothing here has been "
            "shown to be empty.".format(result["why"]),
        )
        return
    if result["state"] == "none":
        doctor.report(
            "OK",
            "trap queue: none waiting -- {}. Log one with a file in trap.d/ when something "
            "costs you time; deciding where it belongs is /oss:curate's job, not the "
            "lane's.".format(result["why"]),
        )
        return
    doctor.report(
        "NOTICE",
        "trap queue: {} waiting for /oss:curate ({}). Not a fault and nothing is blocked -- "
        "fragments are inert until a pass promotes, merges or declines them, and a queue "
        "that carries over is how the pass gets skipped for being too big.".format(
            result["count"], ", ".join(f["name"] for f in result["fragments"])
        ),
    )
