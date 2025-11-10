# Simple Epoch Labels - Publication-Ready Timeline Markers

Simple epoch labels provide publication-ready protocol timeline markers above your traces, similar to those found in scientific papers showing pressure myography experiments.

## Visual Style

The simple epoch system uses a clean, publication-ready design:
- **Simple rectangular bars** with black borders and white fill
- **Stacked semantic rows** (Treatment, Drug, Pressure, Protocol)
- **Automatic collision avoidance** - overlapping epochs stack vertically
- **Minimal visual complexity** - optimized for publication figures

## Example Usage

### Basic Usage in Main Window

```python
from vasoanalyzer.ui.simple_epoch_renderer import SimpleEpoch, events_to_simple_epochs

# Convert existing VasoAnalyzer events to simple epochs
epochs = events_to_simple_epochs(
    event_times=[0, 100, 200, 300],
    event_labels=["20 mmHg", "40 mmHg", "60 mmHg", "80 mmHg"],
    event_label_meta=[
        {"category": "pressure"},
        {"category": "pressure"},
        {"category": "pressure"},
        {"category": "pressure"},
    ],
    default_duration=100.0  # Default bar length in seconds
)

# Set epochs on plot host
plot_host.set_simple_epochs(epochs)
plot_host.set_simple_epochs_visible(True)
```

### Creating Custom Epochs

```python
from vasoanalyzer.ui.simple_epoch_renderer import SimpleEpoch

# Create pressure step epochs
pressure_epochs = [
    SimpleEpoch(
        label="20 mmHg",
        t_start=0,
        t_end=100,
        row="Pressure",
        color="#000000",
        fill="#FFFFFF"
    ),
    SimpleEpoch(
        label="40 mmHg",
        t_start=100,
        t_end=200,
        row="Pressure"
    ),
]

# Create drug application epochs
drug_epochs = [
    SimpleEpoch(
        label="U46619 25nM",
        t_start=150,
        t_end=350,
        row="Drug"
    ),
]

# Combine and display
all_epochs = pressure_epochs + drug_epochs
plot_host.set_simple_epochs(all_epochs)
plot_host.set_simple_epochs_visible(True)
```

## Semantic Row Organization

Epochs are automatically organized into semantic rows (top to bottom):

1. **Treatment** - Bath changes, perfusate switches
2. **Drug** - Drug applications, blockers
3. **Pressure** - Pressure steps, setpoints
4. **Protocol** - Other experimental markers

### Category Mapping

When converting events with `events_to_simple_epochs()`:

| Event Category | Target Row |
|----------------|------------|
| `pressure`, `setpoint` | Pressure |
| `drug`, `blocker` | Drug |
| `bath`, `perfusate` | Treatment |
| Other | Protocol |

## Automatic Collision Handling

When epochs overlap within the same row, they automatically stack into sub-rows:

```
Treatment:  [   PSS   ][   Ca-free PSS   ]
Drug:       [====Drug A====]
            [====Drug B====]    ← Auto-stacked because it overlaps Drug A
Pressure:   [20][40][60][80][100]
```

## Controlling Visibility

```python
# Show epochs
plot_host.set_simple_epochs_visible(True)

# Hide epochs
plot_host.set_simple_epochs_visible(False)

# Check current state
is_visible = plot_host.simple_epochs_visible()
```

## Duration Inference

The `events_to_simple_epochs()` helper automatically infers epoch duration:

1. **Explicit `t_end`** in metadata - uses that directly
2. **Explicit `duration`** in metadata - calculates `t_end = t_start + duration`
3. **Inferred from next event** - uses next event time in same category as `t_end`
4. **Default duration** - uses `default_duration` parameter (default: 60s)

### Example with Duration Metadata

```python
epochs = events_to_simple_epochs(
    event_times=[0, 100],
    event_labels=["PE 1µM", "ACh 10µM"],
    event_label_meta=[
        {"category": "drug", "duration": 120},  # Lasts 120 seconds
        {"category": "drug", "t_end": 250},     # Explicit end time
    ]
)
```

## Publication-Ready Style Guidelines

For optimal publication figures:

1. **Use black/white** - Default colors work for most journals
2. **Keep labels concise** - Abbreviations are common (PE, ACh, etc.)
3. **Organize semantically** - Group by row type
4. **Avoid overlaps** - The system handles stacking, but spacing events improves clarity

## Integration with Existing Events

The system works seamlessly with VasoAnalyzer's existing event system:

```python
# In main window, convert current events to epochs
from vasoanalyzer.ui.simple_epoch_renderer import events_to_simple_epochs

epochs = events_to_simple_epochs(
    event_times=self.event_table_data[0],  # Time column
    event_labels=self.event_table_data[1],  # Label column
    event_label_meta=self.event_label_meta,
)

self.plot_host.set_simple_epochs(epochs)
self.plot_host.set_simple_epochs_visible(True)
```

## Comparison with Full Epoch System

| Feature | Simple Epochs | Full Epoch System (Publication Studio) |
|---------|---------------|----------------------------------------|
| **Visual Style** | Plain rectangles | Bars, boxes, shaded regions |
| **Color** | Black/white | Multi-color by channel |
| **Styles** | One style | bar, box, shade |
| **Emphasis** | None | light, normal, strong |
| **Use Case** | Main trace view | Figure Composer exports |
| **Complexity** | Minimal | Full-featured |

## Tips

1. **Toggle during analysis** - Show epochs when reviewing protocol, hide when analyzing fine details
2. **Duration matters** - Set realistic durations for better visual clarity
3. **Use categories** - Proper categorization enables semantic row organization
4. **Export-friendly** - Design works well in screenshots and exported figures

## Future Enhancements

Planned improvements:
- UI toggle button in toolbar
- Persistence in project UI state
- Customizable colors per row
- Font size adjustment
- Export to publication formats
