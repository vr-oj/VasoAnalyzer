#!/usr/bin/env python3
"""
Comparison test to visualize the difference between old and new lane algorithms.

This script simulates the lane assignment for a set of labels and shows
how they distribute across lanes with first-fit vs best-fit algorithms.
"""

def first_fit_lane_selection(px: float, width: float, lane_end_px: list[float]) -> int:
    """Original first-fit algorithm - returns first available lane."""
    for lane_index, lane_tail in enumerate(lane_end_px):
        if px >= lane_tail:
            return lane_index
    # If no lane fits perfectly, use the one that's least occupied
    return min(range(len(lane_end_px)), key=lambda i: lane_end_px[i])


def best_fit_lane_selection(px: float, width: float, lane_end_px: list[float]) -> int:
    """Improved best-fit algorithm - picks lane with most room remaining."""
    candidates = []
    for lane_index, lane_tail in enumerate(lane_end_px):
        if px >= lane_tail:  # Label fits without overlap
            candidates.append((lane_index, lane_tail))
    
    if candidates:
        # Choose the lane with the earliest end position (most room remaining)
        best_lane = min(candidates, key=lambda x: x[1])[0]
        return best_lane
    
    # If no lane fits perfectly, use the one that ends earliest
    return min(range(len(lane_end_px)), key=lambda i: lane_end_px[i])


def simulate_placement(labels, lane_selector, num_lanes=3):
    """Simulate label placement with a given lane selection algorithm."""
    lane_end_px = [float("-inf")] * num_lanes
    buffer_px = 12.0
    placements = []
    
    for i, (px, width) in enumerate(labels):
        lane_idx = lane_selector(px, width, lane_end_px)
        lane_end_px[lane_idx] = px + width + buffer_px
        placements.append((i, px, width, lane_idx))
    
    return placements


def visualize_placement(placements, title):
    """Print a simple ASCII visualization of label placement."""
    print(f"\n{title}")
    print("=" * 70)
    
    # Count labels per lane
    lane_counts = {}
    for _, _, _, lane_idx in placements:
        lane_counts[lane_idx] = lane_counts.get(lane_idx, 0) + 1
    
    # Print lane distribution
    max_lane = max(p[3] for p in placements)
    for lane in range(max_lane + 1):
        count = lane_counts.get(lane, 0)
        bar = "█" * count
        print(f"Lane {lane}: {bar} ({count} labels)")
    
    # Print timeline view
    print("\nTimeline View:")
    max_lane = max(p[3] for p in placements)
    for lane in range(max_lane, -1, -1):
        line = f"Lane {lane}: "
        lane_labels = sorted([(px, i) for i, px, _, l in placements if l == lane])
        for px, i in lane_labels:
            # Add spacing proportional to position
            spaces = int(px / 50)  # Scale down for display
            line += " " * (spaces - len(line) + 8) + f"[L{i}]"
        print(line)
    print("-" * 70)


def main():
    # Simulate 12 labels at different positions (similar to your screenshots)
    # Position in pixels, width in pixels
    labels = [
        (100, 120),   # Label 0: "Set pressure = 20.0 mmHg"
        (600, 120),   # Label 1: "Set pressure = 40.0 mmHg"
        (1200, 120),  # Label 2: "Set pressure = 60.0 mmHg"
        (1800, 120),  # Label 3: "Set pressure = 80.0 mmHg"
        (2400, 120),  # Label 4: "Set pressure = 100.0 mmHg"
        (3000, 120),  # Label 5: "Set pressure = 120.0 mmHg"
        (3100, 120),  # Label 6: "Set pressure = 120.0 mmHg" (close to 5)
        (3600, 120),  # Label 7: "Set pressure = 100.0 mmHg"
        (4200, 120),  # Label 8: "Set pressure = 80.0 mmHg"
        (4800, 120),  # Label 9: "Set pressure = 60.0 mmHg"
        (5400, 120),  # Label 10: "Set pressure = 40.0 mmHg"
        (6000, 120),  # Label 11: "Set pressure = 20.0 mmHg"
    ]
    
    print("=" * 70)
    print("LANE ASSIGNMENT ALGORITHM COMPARISON")
    print("=" * 70)
    print(f"\nSimulating placement of {len(labels)} labels across 3 lanes")
    print("Each label is ~120px wide with 12px buffer")
    
    # Test first-fit (old algorithm)
    first_fit_placements = simulate_placement(labels, first_fit_lane_selection)
    visualize_placement(first_fit_placements, "FIRST-FIT (Old Algorithm)")
    
    # Test best-fit (new algorithm)
    best_fit_placements = simulate_placement(labels, best_fit_lane_selection)
    visualize_placement(best_fit_placements, "BEST-FIT (New Algorithm)")
    
    # Calculate distribution metrics
    print("\n" + "=" * 70)
    print("DISTRIBUTION METRICS")
    print("=" * 70)
    
    def calc_distribution(placements):
        lane_counts = {}
        for _, _, _, lane_idx in placements:
            lane_counts[lane_idx] = lane_counts.get(lane_idx, 0) + 1
        return lane_counts
    
    first_dist = calc_distribution(first_fit_placements)
    best_dist = calc_distribution(best_fit_placements)
    
    print("\nFirst-Fit Distribution:")
    for lane, count in sorted(first_dist.items()):
        pct = (count / len(labels)) * 100
        print(f"  Lane {lane}: {count:2d} labels ({pct:5.1f}%)")
    
    print("\nBest-Fit Distribution:")
    for lane, count in sorted(best_dist.items()):
        pct = (count / len(labels)) * 100
        print(f"  Lane {lane}: {count:2d} labels ({pct:5.1f}%)")
    
    # Calculate balance score (lower is better - perfect balance = 0)
    def balance_score(dist, num_lanes):
        ideal = len(labels) / num_lanes
        return sum(abs(dist.get(i, 0) - ideal) for i in range(num_lanes))
    
    first_balance = balance_score(first_dist, 3)
    best_balance = balance_score(best_dist, 3)
    
    print(f"\nBalance Score (lower = better):")
    print(f"  First-Fit: {first_balance:.1f}")
    print(f"  Best-Fit:  {best_balance:.1f}")
    print(f"  Improvement: {((first_balance - best_balance) / first_balance * 100):.1f}%")
    
    print("\n" + "=" * 70)
    print("CONCLUSION")
    print("=" * 70)
    print("\nBest-Fit algorithm:")
    print("  ✓ Distributes labels more evenly across lanes")
    print("  ✓ Reduces visual clutter")
    print("  ✓ Makes better use of available vertical space")
    print("  ✓ Improves readability")
    print("\nFirst-Fit algorithm:")
    print("  ✗ Tends to cluster labels in lower lanes")
    print("  ✗ Leaves upper lanes underutilized")
    print("  ✗ Creates more visual density in one area")
    print("=" * 70)


if __name__ == "__main__":
    main()
