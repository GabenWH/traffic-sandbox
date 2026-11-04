# Building resources, shopping and construction companies

Place **Construction company** through the existing building tool. It has eight
jobs. Residents can be assigned with `CitySimulation.assign_workplace(person_id,
company_id)` or receive jobs through the existing job assignment process.

Workers commute to their employer, travel to an available construction site,
contribute labor while present, and return to the company when the site finishes.
Their `workplace` stays the company; `worksite` identifies the temporary site.
At shift end they return via the company to retrieve any personal car.

An empty city can bootstrap housing and the company through regional crews. Once
residents and an operational company exist, building construction uses resident
labor. This switch survives saving and does not revert when the company closes.
Road demolition still uses regional crews. Dedicated crew vans are not modeled:
site travel uses the existing walking/transit planner.

Residents automatically collect food from reachable markets when home supplies are
low. `request_shopping(person_id, market_id, resource='food', target=3)` also exposes
collection to scenarios. Supplies are reserved at departure and added to the home
only after return. Collection and delivery both count toward incoming supplies.
`request_visit(..., 'meal')` and `request_visit(..., 'care')` retain consumption at
service buildings. Use `request_shopping`, not a shopping-purpose `request_visit`.

Construction and consumer buildings share ResourceInventory transfer, shortage and
recipe operations, plus the physical resource catalogue and truck-load limits.
Regional construction trips and persistent local truck logistics remain distinct
transport adapters; local trucks still load, unload, park and return.

The consumer catalogue uses illustrative portions, batches and doses. It does not
reinterpret existing food stocks as tonnes from the separate prototype branch.
Wages, skills, utilities and emission recipes are not part of this change.
