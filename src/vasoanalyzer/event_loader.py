import pandas as pd

def load_events(file_path):
	# Try to auto-detect delimiter
	with open(file_path, 'r') as f:
		first_line = f.readline()
		delimiter = ',' if ',' in first_line else '\t'

	df = pd.read_csv(file_path, delimiter=delimiter)

	# Auto-detect columns
	label_col = next((col for col in df.columns if 'label' in col.lower()), df.columns[0])
	time_col  = next((col for col in df.columns if 'time' in col.lower()), df.columns[1])
	frame_col = next((col for col in df.columns if 'frame' in col.lower()), None)

	# Convert time to seconds
	if df[time_col].dtype == 'object':
		time_sec = pd.to_timedelta(df[time_col]).dt.total_seconds()
	else:
		time_sec = df[time_col]

	labels = df[label_col].astype(str).tolist()
	times = time_sec.tolist()

	frames = None
	if frame_col:
		frames = df[frame_col].tolist()

	return labels, times, frames
