import sys
import os

# Make the package importable when tests run straight from a checkout
# (no installation required).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
