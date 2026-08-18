# Freeway Simulator

An interactive, dependency-free Python freeway simulation. Cars enter two lanes at varied speeds and slow down to maintain a gap behind slower traffic. Both input lanes explicitly join a separate post-merge lane. During the merge, each lane treats cars in the other lane (and, near the end, the post-merge lane) as gradually solidifying phantom counterparts: they have no effective size or collision blocking at the start of the merge, lightly affect acceleration at first, and become normal following obstacles by the lane's end.

Run it with Python 3:

```bash
python3 freeway_simulator.py
```

Use the **Simulation** dropdown for Pause, Add car, and Clear traffic. Select **Inspect** for simulation speed, traffic target, live metrics, and editable following gaps. Right-click either lane to open its context menu.

Right-click a lane and choose **Add speed-limit sign** to post a limit from that point onward. Right-click an existing sign to change or delete it. Cars target the posted limit plus an individual preference of -5 to +10 MPH internally.

Use the **Units** menu to switch between Imperial (mph/feet) and Metric (km/h/metres). Change `DEFAULT_UNIT_SYSTEM` in `config.py` to select the default for new windows. The traffic model keeps one pixel as one foot of roadway and stores speed limits in MPH so physics and saves do not change when the display unit changes. The code is split by responsibility: `models.py` contains lane and car data, `simulation.py` contains traffic rules, and `ui.py` contains the Tkinter interface.

`saves/current-merge-demo.json` preserves the current fixed merge scenario as a loadable baseline. It is intentionally traffic-free so each load starts from the same road configuration.

The city-builder prototype starts on a 5,000 × 3,500 grassy terrain map with deterministic trees. Use the middle mouse button to pan, the mouse wheel to zoom toward the cursor, and **Reset view** to return to the starting view. Camera movement also applies to the merge-demo road, traffic, and speed-limit signs.

Use the **File** and **Simulation** dropdown tools just as before. **Inspect** opens its panel in the bottom-left corner of the main canvas; while it is active, left-click a car, speed-limit sign, or lane to inspect and edit supported fields, or click empty space for global stats. Fields use sliders, validated text input, or read-only labels. The toolbar order and enabled tools are editable in [`ui_tools/toolbar.json`](ui_tools/toolbar.json); each tool has its own module in `ui_tools/tools/`. Run `python3 -m ui_tools.sync_toolbar` after adding a module, or `bash scripts/watch_toolbar_tools.sh` to keep that JSON updated on Linux. See [`docs/TOOLS.md`](docs/TOOLS.md) for the full tool workflow.

Requires Python with tkinter (included by default with most desktop Python installations).
