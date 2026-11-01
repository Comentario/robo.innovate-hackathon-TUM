# Junction cleanup — revision 19

Open `artifacts/greenfield_19/index.html`. This supersedes revision 18 visually; its recorded production run is unchanged.

Removed all painted arrows, the redundant inlet stop inside the reject-pusher envelope, and the straight outer rail sections crossing the merge/extraction openings. The inlet is metered by its servo drive. Rebuilt both loop photoeye mounts with an under-deck crossmember, upright and cantilever. Replaced the small unsupported outlet blade assembly with a mounted pivot guide, shaft, motor and structural bracket. All eight cells share these changes.

Verification: offline browser initialized without runtime errors. Captured inlet/outlet closeups and three recorded phases per junction. Static clearance audit: 168,141 strokes, 6,922 static bounds, 3,338,195 candidate checks, zero detected intersections. Curve checks are sampled; moving guide contact and material-to-material collisions are not certified. Screenshots and audit evidence are in the artifact's `verification/` directory.

The same run SHA-256 confirms unchanged timing and KPIs: 4,236.9 conforming shipped bricks/h for the synthetic batch. This is a geometric demo cleanup, not independent validation of industrial steering or friction.
