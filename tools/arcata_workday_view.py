"""Show snapshots from the Arcata stress runner without blocking its simulation."""
import json
import queue
import sys
import threading
import time
import tkinter as tk


def zoom_at(zoom, pan, pointer, viewport, factor):
    """Scale around the pointer instead of sliding a panned map sideways."""
    new_zoom = max(.5, min(30, zoom * factor))
    ratio = new_zoom / zoom
    offset = (pointer[0] - viewport[0] / 2, pointer[1] - viewport[1] / 2)
    new_pan = tuple(offset[i] - (offset[i] - pan[i]) * ratio for i in (0, 1))
    return new_zoom, new_pan


def main():
    root = tk.Tk()
    root.title('Arcata workday stress test')
    root.geometry('1100x760')
    status = tk.StringVar(value='Waiting for the simulation…')
    tk.Label(root, textvariable=status, anchor='w', justify='left', font=('TkDefaultFont', 11)).pack(fill='x', padx=8, pady=5)
    canvas = tk.Canvas(root, bg='#edf1e9', highlightthickness=0)
    canvas.pack(fill='both', expand=True)
    messages = queue.Queue()
    state = {'roads': [], 'buildings': [], 'snapshot': None, 'received': None,
             'zoom': 1.0, 'pan': [0, 0], 'anchor': None, 'finished': False,
             'stage': 'loading map'}

    def read_messages():
        try:
            for line in sys.stdin:
                messages.put(json.loads(line))
        finally:
            messages.put({'kind': 'finished'})
    threading.Thread(target=read_messages, daemon=True).start()

    def draw():
        canvas.delete('all')
        roads = state['roads']
        points = [p for road in roads for p in road]
        if not points:
            return
        minx = min(p[0] for p in points); maxx = max(p[0] for p in points)
        miny = min(p[1] for p in points); maxy = max(p[1] for p in points)
        width = max(1, canvas.winfo_width()); height = max(1, canvas.winfo_height())
        scale = min((width-40)/max(1, maxx-minx), (height-40)/max(1, maxy-miny))*state['zoom']
        def xy(p):
            return (width/2+(p[0]-(minx+maxx)/2)*scale+state['pan'][0],
                    height/2+(p[1]-(miny+maxy)/2)*scale+state['pan'][1])
        for road in roads:
            if len(road) > 1:
                canvas.create_line(*(v for p in road for v in xy(p)), fill='#8e9a9f', width=1)
        for x,y,kind in state['buildings']:
            px,py=xy((x,y)); color='#d5794f' if kind != 'home' else '#588bb0'
            canvas.create_rectangle(px-2,py-2,px+2,py+2,fill=color,outline='')
        snap = state['snapshot']
        if snap:
            for x,y,kind in snap['vehicles']:
                px,py=xy((x,y)); color='#e5a800' if kind=='bus' else '#e63845'
                canvas.create_oval(px-4,py-4,px+4,py+4,fill=color,outline='white')

    def poll():
        dirty = False
        while True:
            try: msg=messages.get_nowait()
            except queue.Empty: break
            if msg['kind']=='map':
                state['roads']=msg['roads'];state['buildings']=msg['buildings'];dirty=True
            elif msg['kind']=='snapshot':
                state['snapshot']=msg;state['received']=time.monotonic();dirty=True
            elif msg['kind']=='progress': state['stage']=msg['stage'].replace('_',' ')
            elif msg['kind']=='finished': state['finished']=True
        snap=state['snapshot']
        if snap:
            r=snap['report']; seconds=int(snap['time']); age=int(time.monotonic()-state['received'])
            status.set(f"{seconds//3600%24:02d}:{seconds//60%60:02d}  |  Population {r['population']}  |  Home {r['at_home']}  |  Work {r['at_work']}  |  Commuting {r['commuting']}  |  Active vehicles {len(snap['vehicles'])}\n"
                       f"Snapshot {age}s ago{' — runner stopped' if state['finished'] else ''}  |  Blue: homes  Orange: workplaces  Yellow: buses  Red: other vehicles  |  Drag to pan, wheel to zoom")
        elif state['finished']: status.set('Runner stopped before the first simulation snapshot.')
        else: status.set(f"Preparing scenario: {state['stage']}…")
        if dirty: draw()
        root.after(500,poll)

    def drag_start(event): state['anchor']=(event.x,event.y)
    def drag(event):
        if state['anchor']:
            x,y=state['anchor'];state['pan'][0]+=event.x-x;state['pan'][1]+=event.y-y
            state['anchor']=(event.x,event.y);draw()
    def zoom(event):
        factor = 1.2 if event.delta > 0 or event.num == 4 else 1/1.2
        state['zoom'], pan = zoom_at(state['zoom'], state['pan'], (event.x, event.y),
                                    (canvas.winfo_width(), canvas.winfo_height()), factor)
        state['pan'][:] = pan
        draw()
    canvas.bind('<Configure>',lambda event:draw())
    canvas.bind('<ButtonPress-1>',drag_start);canvas.bind('<B1-Motion>',drag)
    canvas.bind('<MouseWheel>',zoom);canvas.bind('<Button-4>',zoom);canvas.bind('<Button-5>',zoom)
    poll();root.mainloop()


if __name__ == '__main__':
    main()
