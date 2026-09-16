# What these benchmarks mean for the observatory

## Two CPU modes

1. **One large world:** one native simulation with multiple OpenMP threads. Its scaling is measured separately from independent jobs.
2. **A family of worlds:** multiple one-thread worker processes. Each explores a different orbit, encounter angle or initial density. Do not give each worker all CPU threads: that oversubscribes the machine.

Start with whichever workload answers the experiment's question. The fastest worker count and fastest thread count can differ.

## Compute and playback

Physics produces snapshots, independent of display refresh. A viewer interpolates between saved positions for smooth playback. Interpolation improves presentation but does not add physical precision. Report both physics time and playback time.

A proposed first galaxy experiment needs an isolated equilibrium model before adding a second galaxy. Include stellar disk and dark matter, define physical units, and verify timestep and tree-opening-angle convergence. The benchmark's uniform cloud is intentionally a computational test fixture, not a galaxy model.

## Data volume

Uncompressed positions only, three coordinates per particle:

| Particles | Float32 per snapshot | 1,000 snapshots |
|---:|---:|---:|
| 10,000 | 0.12 MB | 120 MB |
| 100,000 | 1.2 MB | 1.2 GB |
| 300,000 | 3.6 MB | 3.6 GB |
| 1,000,000 | 12 MB | 12 GB |

Decimal units. Velocities double these values; float64 doubles them again. IDs, masses, metadata and checkpoint structures add overhead. Use sparse resumable checkpoints plus downsampled playback snapshots; a simulation fitting in RAM does not imply storing every step is inexpensive.

## Evidence required before a long scientific run

- Defined physical question, mass distribution, units and duration.
- Short-run stability of the initial galaxy model in isolation.
- Agreement under smaller timesteps and tighter tree settings.
- Energy/angular-momentum tracking and actual event definitions.
- Checkpoint/restart comparison and bounded storage.

No cloud services or paid APIs are required for the benchmark. Other solvers and GPU implementations may improve throughput; these CPU results do not measure that potential.
