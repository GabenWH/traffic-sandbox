"""Launch the interactive freeway traffic simulator."""

import tkinter as tk

from ui import FreewaySimulator


if __name__ == "__main__":
    app = tk.Tk()
    FreewaySimulator(app)
    app.mainloop()
