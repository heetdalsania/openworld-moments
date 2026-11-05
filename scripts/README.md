# Scripts

Repository automation. Scripts must work on Windows and Linux CI runners, or be
called only from a job that pins its OS.

- `check-dco.sh` — verifies every commit in a range has a `Signed-off-by` trailer.
