# ticket_app_backend
building a backend sytem for ticket sale

## Nearby events

`GET /events/nearby/?latitude=6.5244&longitude=3.3792&radius_km=10&page=1`

- `latitude` and `longitude` are required user coordinates.
- `radius_km` is the dropdown filter: `5`, `10`, `20`, or `30` (defaults to `5`).
- `page` defaults to `1` and accepts `1` through `1000`; each response contains
  at most 10 events, ordered from closest to farthest. The response's
  `pagination` object supplies the next and previous page numbers plus the
  total number of matching events.

When a user changes the radius dropdown, request the endpoint again with the
new `radius_km` value and reset `page` to `1`. The backend has no frontend in
this repository, so the UI performs that refresh.
