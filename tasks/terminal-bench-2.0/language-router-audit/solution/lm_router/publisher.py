from pathlib import Path


def finalize_runtime_outputs(output_dir):
    Path(output_dir).mkdir(parents=True, exist_ok=True)
