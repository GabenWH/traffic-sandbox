"""Launch the interactive freeway traffic simulator."""

import tkinter as tk
import argparse

from ui import FreewaySimulator


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traffic-engine', choices=('legacy', 'data_first', 'native'), default='data_first',
                        help='Constructed-road vehicle simulation engine')
    return parser.parse_args(argv)


def main(argv=None):
    options = parse_args(argv)
    app = tk.Tk()
    FreewaySimulator(app, traffic_engine=options.traffic_engine)
    app.mainloop()


if __name__ == "__main__":
    main()
