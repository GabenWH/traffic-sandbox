import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from humboldt_water_transit import *
from itertools import product
from json import dumps
from pathlib import Path

results={}
for fleet,demand,rise,restrict,closed,hardened in product(('mixed','ferry','hovercraft','bus'),(500,2000,8000),(0,3,6),(False,True),(False,True),(False,True)):
    config=Configuration(fleet=fleet,daily_trips=demand,sea_rise_ft=rise,sensitive_exclusion=restrict,road_closure=closed,hardened_terminals=hardened)
    result=simulate(config)
    key='|'.join(map(str,(fleet,demand,rise,int(restrict),int(closed),int(hardened))))
    results[key]={k:result[k] for k in ('requested','served','unserved','mean_door_to_door_min','p90_door_to_door_min','fleet','energy_kwh','vehicle_miles','passenger_boardings','passenger_miles','lines')}

terminals=[t.__dict__ for t in TERMINALS]
lines=[l.__dict__ | {'travel_min':l.travel_min} for l in LINES]
root=Path(__file__).resolve().parents[1]
html=(root / 'humboldt_transit_app.template.html').read_text()
html=html.replace('/*__NETWORK__*/','const NETWORK='+dumps({'terminals':terminals,'lines':lines},separators=(',',':'))+';')
html=html.replace('/*__RESULTS__*/','const RESULTS='+dumps(results,separators=(',',':'))+';')
(root / 'humboldt_transit_app.html').write_text(html)
print(f'Generated {len(results)} verified scenario outputs, app bytes {len(html)}')