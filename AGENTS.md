# Environment Rules

- Do not install Python packages into the `base` conda environment.
- Before running any package install command, check the active environment and switch to the project-specific environment if one exists.
- For this repository, prefer the `moonspeak` conda environment for Python/package work.
- If a dependency is missing and no project environment is active, stop and verify the target environment first instead of installing into `base`.
