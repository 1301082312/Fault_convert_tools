"""Double-click (or `python run_gui.py`) to open the Fault_convert_tools window."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fault_convert.gui import main  # noqa: E402

main()
