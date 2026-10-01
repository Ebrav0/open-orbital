"""Repository paths. Secrets never live in the package directory."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'work' / 'lab-data'
OBSERVATORY = ROOT / 'outputs' / 'observatory'
OPENMP = ROOT / 'work' / 'openmp'
ENV_FILE = DATA / 'lab.env'
RCLONE_CONFIG = DATA / 'rclone.conf'
DATABASE = DATA / 'lab.sqlite'
SCRATCH = DATA / 'scratch'
CONFIG_FILE = DATA / 'lab.toml'
