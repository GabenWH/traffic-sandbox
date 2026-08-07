# Freeway Simulator

An interactive, dependency-free Python freeway simulation. Cars enter two lanes at varied speeds and slow down to maintain a gap behind slower traffic. Both input lanes explicitly join a separate post-merge lane. During the merge, each lane treats cars in the other lane (and, near the end, the post-merge lane) as gradually solidifying phantom counterparts: they have no effective size or collision blocking at the start of the merge, lightly affect acceleration at first, and become normal following obstacles by the lane's end.

Run it with Python 3:

```bash
python3 freeway_simulator.py
```

Use **Pause**, **Add car**, and **Clear traffic** to control the scene. The sliders adjust simulation speed and traffic level. Right-click either lane to select it; its preferred following gap can then be adjusted in the toolbar or entered precisely from the context menu. The toolbar also shows exits during the most recent simulated minute.

Right-click a lane and choose **Add speed-limit sign** to post a limit from that point onward. Right-click an existing sign to change or delete it. Cars target the posted MPH plus an individual preference of -5 to +10 MPH.

The toolbar reports the active fleet's average speed in MPH (using one pixel as one foot of roadway). The code is split by responsibility: `models.py` contains lane and car data, `simulation.py` contains traffic rules, and `ui.py` contains the Tkinter interface.

Requires Python with tkinter (included by default with most desktop Python installations).
