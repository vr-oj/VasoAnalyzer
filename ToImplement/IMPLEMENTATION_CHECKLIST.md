# Implementation Checklist

## ☑️ Pre-Implementation

- [ ] Read `README.md` to understand the solution
- [ ] Review `BEFORE_AFTER_DIAGRAM.md` to see what will change
- [ ] Run `test_lane_algorithms.py` to verify the algorithm works
- [ ] Backup your current `event_labels_v3.py` file

## ☑️ Implementation

- [ ] Copy `event_labels_v3_improved.py` to your project directory
- [ ] Rename it to `event_labels_v3.py` (or whatever you use)
- [ ] Verify the file copied correctly (check file size ~34KB)
- [ ] No other changes needed - the file is a drop-in replacement

## ☑️ Testing

- [ ] Run your application with the new file
- [ ] Check that labels now spread across multiple lanes
- [ ] Verify labels are clearly separated from dashed lines (not overlapping)
- [ ] Confirm labels don't extend beyond plot boundaries
- [ ] Test with different zoom levels
- [ ] Test with different numbers of events (few vs many)

## ☑️ Verification

### Visual Checks
- [ ] Labels are distributed across 2-3 lanes (not all in one)
- [ ] ~12px gap between label text and dashed event line
- [ ] Labels don't overlap with each other
- [ ] Labels don't get cut off at plot edges
- [ ] Vertical dashed lines are clearly visible
- [ ] Overall appearance is clean and professional

### Functional Checks
- [ ] All events are still labeled correctly
- [ ] Label text matches event names
- [ ] Clicking/hovering on labels still works (if applicable)
- [ ] Priority system still functions (high priority visible)
- [ ] Pinned labels stay pinned
- [ ] Custom colors/fonts still apply
- [ ] All three modes work (vertical, h_inside, h_belt)

## ☑️ Fine-Tuning (Optional)

If you need adjustments, modify these parameters:

### More Lanes for Dense Plots
```python
# In LayoutOptionsV3, increase lanes from 3 to 4 or 5
lanes: int = 4
```
- [ ] Adjusted lane count if needed

### More/Less Spacing
```python
# In _draw_horizontal_inside, adjust spacing
preferred_gap_px = 15.0  # Increase from 12.0 for more space
buffer_px = 15.0         # Increase for more space between labels
```
- [ ] Adjusted horizontal spacing if needed

### Edge Margins
```python
# In _draw_horizontal_inside, adjust margins
margin_px = 6.0  # Increase from 4.0 for more edge space
```
- [ ] Adjusted margins if needed

## ☑️ Troubleshooting

If issues arise, check:

### Labels Still Overlapping
- [ ] Increased `lanes` parameter
- [ ] Increased `buffer_px` parameter
- [ ] Reduced font size in settings
- [ ] Checked `min_px` clustering threshold

### Labels Cut Off at Edges
- [ ] Increased `margin_px` parameter
- [ ] Enabled label truncation
- [ ] Reduced font size for long labels

### Labels Too Far from Lines
- [ ] Decreased `preferred_gap_px` from 12 to 10
- [ ] Adjusted per-label `x_offset_px` override

### Algorithm Not Working
- [ ] Verified correct file was copied
- [ ] Checked Python version (needs 3.7+)
- [ ] Reviewed `changes.diff` to ensure changes applied
- [ ] Checked for import errors in console

## ☑️ Documentation

- [ ] Updated your project docs to reference the fix
- [ ] Noted any custom parameter changes you made
- [ ] Saved this checklist for future reference
- [ ] Kept `QUICK_REFERENCE.md` handy for parameter lookup

## ☑️ Success Criteria

Your implementation is successful when:

✅ Labels spread across multiple lanes (not clustering)
✅ ~33% of labels per lane (even distribution)
✅ Clear visual gap between labels and dashed lines
✅ All labels visible and readable
✅ No overlap or cutoff issues
✅ Professional, clean appearance

## 📊 Metrics to Verify Success

Run the test script to verify:
```bash
python3 test_lane_algorithms.py
```

Expected output:
- First-Fit: 91.7% in one lane (old behavior)
- Best-Fit: 33.3% per lane (new behavior)
- Improvement: 100%

## 🎉 Completion

- [ ] All checks passed
- [ ] Application runs correctly
- [ ] Labels display properly
- [ ] Team/users notified of improvement
- [ ] Documentation updated

**Congratulations! Your event labels are now properly distributed and clearly readable!**

---

## 📞 Need Help?

If you encounter issues:
1. Check `QUICK_REFERENCE.md` → Common solutions
2. Read `implementation_guide.md` → Detailed steps  
3. Review `event_labels_analysis_and_fixes.md` → Technical details
4. Compare with `changes.diff` → Verify correct changes applied

## 🔄 Rollback (If Needed)

If you need to revert:
```bash
cp event_labels_v3_backup.py event_labels_v3.py
```

Then review the documentation to understand what might have gone wrong.
