# Separator visual fix — revision 23

Open `artifacts/greenfield_23/index.html`.

Removed the coincident steel/dark backing plates that caused depth flicker. Repositioned the fixed lower support behind the moving webs, separated the guide bushings from the cylinder body, and added a defined piston coupling on the moving crosshead. The visible piston now ends at that coupling; it no longer passes through the lower bracket. Closed the small gap between the yellow guide and its backing plate.

Reviewed extended/retracted closeups in the browser without runtime errors. Static clearance audit: 164,659 strokes, 8,042 bounds, 3,184,750 candidate checks, zero detected intersections. Moving contact is not certified by this static check. Production tracks and KPIs are byte-identical to revision 20; this is a visual assembly correction only. Evidence is under the artifact's `verification/` directory.
