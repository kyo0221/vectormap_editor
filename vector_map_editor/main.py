from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from vector_map_editor.app.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
