"""Launch the interactive freeway traffic simulator."""

import tkinter as tk
import argparse

from ui import FreewaySimulator


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--traffic-engine', choices=('cpp',), default='cpp',
                        help='Constructed-road vehicle simulation engine')
    parser.add_argument('--viewer',choices=('panda','tk'),default='panda',
                        help='Native shared Panda viewer (default) or legacy Tk map')
    parser.add_argument('--volumetric-clouds', action='store_true',
                        help='Try the experimental volumetric sky in the 3D view')
    return parser.parse_args(argv)


def main(argv=None):
    options = parse_args(argv)
    app = tk.Tk()
    FreewaySimulator(app, traffic_engine=options.traffic_engine, viewer=options.viewer,
                     volumetric_clouds=options.volumetric_clouds)
    app.mainloop()


if __name__ == "__main__":
    main()
