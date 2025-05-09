from PyQt5.QtWidgets import (
	QDialog, QVBoxLayout, QLabel, QPushButton, QFileDialog, QComboBox,
	QTableWidget, QTableWidgetItem, QHBoxLayout, QMessageBox
)
from openpyxl import load_workbook
import os, sys, subprocess, time

class ExcelMappingDialog(QDialog):
	def __init__(self, parent, event_data):
		super().__init__(parent)
		self.setWindowTitle("Map Events to Excel")
		self.event_data = event_data
		self.excel_path = None
		self.wb = None
		self.ws = None
		self.current_row = 3
		self.selected_column = None
		self.history = []

		self.layout = QVBoxLayout(self)
		self.instructions = QLabel("Step 1: Select Excel file")
		self.layout.addWidget(self.instructions)

		self.load_button = QPushButton("Load Excel Template")
		self.load_button.clicked.connect(self.load_excel)
		self.layout.addWidget(self.load_button)

		self.column_selector = QComboBox()
		self.column_selector.addItems([chr(i) for i in range(66, 91)])
		self.column_selector.setEnabled(False)
		self.layout.addWidget(QLabel("Select column to populate:"))
		self.layout.addWidget(self.column_selector)

		self.cell_label = QLabel("Next Excel Cell: N/A")
		self.layout.addWidget(self.cell_label)

		self.event_table = QTableWidget()
		self.event_table.setColumnCount(4)
		self.event_table.setHorizontalHeaderLabels(["EventLabel", "Time (s)", "Frame", "ID (\u00b5m)"])
		self.event_table.setEditTriggers(QTableWidget.NoEditTriggers)
		self.event_table.cellClicked.connect(self.map_event_to_excel)
		self.layout.addWidget(self.event_table)
		self.event_table.setMinimumWidth(400)
		self.event_table.horizontalHeader().setStretchLastSection(True)

		self.button_layout = QHBoxLayout()
		self.skip_button = QPushButton("Skip")
		self.skip_button.clicked.connect(self.skip_cell)
		self.undo_button = QPushButton("Undo Last")
		self.undo_button.clicked.connect(self.undo_last)
		self.done_button = QPushButton("Done")
		self.done_button.clicked.connect(self.finish_and_save)
		self.button_layout.addWidget(self.skip_button)
		self.button_layout.addWidget(self.undo_button)
		self.button_layout.addWidget(self.done_button)
		self.layout.addLayout(self.button_layout)

		self.populate_event_table()

	def populate_event_table(self):
		self.event_table.setRowCount(len(self.event_data))
		for i, event in enumerate(self.event_data):
			if isinstance(event, dict):
				label = event.get("EventLabel", "")
				time = event.get("Time (s)", "")
				frame = event.get("Frame", "")
				id_val = event.get("ID (\u00b5m)", "")
			else:
				label, time, id_val = event
			self.event_table.setItem(i, 0, QTableWidgetItem(str(label)))
			self.event_table.setItem(i, 1, QTableWidgetItem(str(time)))
			self.event_table.setItem(i, 2, QTableWidgetItem(str(frame)))
			self.event_table.setItem(i, 3, QTableWidgetItem(str(id_val)))
		self.event_table.resizeColumnsToContents()

	def load_excel(self):
		path, _ = QFileDialog.getOpenFileName(self, "Select Excel File", "", "Excel Files (*.xlsx)")
		if path:
			try:
				self.wb = load_workbook(path)
				self.ws = self.wb.active
				self.excel_path = path
				self.column_selector.setEnabled(True)
				self.instructions.setText("Step 2: Select column, then click events to assign")
				self.update_cell_label()
			except Exception as e:
				QMessageBox.critical(self, "Error", f"Failed to load Excel file:\n{e}")

	def get_current_cell(self):
		col_letter = self.column_selector.currentText()
		return f"{col_letter}{self.current_row}" if col_letter else None

	def update_cell_label(self):
		col_letter = self.column_selector.currentText()
		cell = f"{col_letter}{self.current_row}" if col_letter else "N/A"
		description = ""
		if self.ws:
			try:
				desc_value = str(self.ws[f"A{self.current_row}"].value)
				if desc_value:
					description = f" *{desc_value}*"
			except:
				pass
		self.cell_label.setText(f"Next Excel Cell: {cell}{description}")

	def map_event_to_excel(self, row, column):
		if not self.ws or not self.column_selector.currentText():
			return
		try:
			col_letter = self.column_selector.currentText()
			value_raw = self.event_table.item(row, 2).text()
			target_cell = f"{col_letter}{self.current_row}"
			try:
				value = float(value_raw)
			except ValueError:
				value = value_raw
			prev_value = self.ws[target_cell].value
			self.history.append((target_cell, prev_value))
			self.ws[target_cell] = value
			self.wb.save(self.excel_path)
			self.current_row += 1
			self.update_cell_label()
		except Exception as e:
			QMessageBox.warning(self, "Mapping Error", f"Failed to assign value: {e}")

	def skip_cell(self):
		self.current_row += 1
		self.update_cell_label()

	def undo_last(self):
		if not self.history:
			QMessageBox.information(self, "Undo", "Nothing to undo.")
			return
		cell, old_value = self.history.pop()
		self.ws[cell] = old_value
		self.wb.save(self.excel_path)
		self.current_row = int(''.join(filter(str.isdigit, cell)))
		self.update_cell_label()

	def finish_and_save(self):
		if self.wb and self.excel_path:
			try:
				self.wb.save(self.excel_path)
				reopen_excel_file_crossplatform(self.excel_path)
				self.accept()
			except Exception as e:
				QMessageBox.critical(self, "Error", f"Failed to save Excel file:\n{e}")

# Auto-update utility
def update_excel_file(excel_path, event_table_data, start_row=3, column_letter="B"):
    try:
        wb = load_workbook(excel_path)
        ws = wb.active
        for i, (_, _, frame, _) in enumerate(event_table_data):  # Now unpacking 4 values
            cell = f"{column_letter}{start_row + i}"
            ws[cell] = frame  # Use frame instead of ID
        wb.save(excel_path)
        print(f"🔄 Excel file updated with frame values in column {column_letter}.")
    except Exception as e:
        print(f"❌ Failed to update Excel file:\n{e}")

# Cross-platform file reopening logic
def reopen_excel_file_crossplatform(path):
	try:
		time.sleep(1)  # prevent race condition with autosave
		if sys.platform == "darwin":
			applescript = f'''
			tell application "Microsoft Excel"
				try
					close (documents whose name is "{os.path.basename(path)}") saving yes
				end try
				open POSIX file "{path}"
				activate
			end tell
			'''
			subprocess.call(["osascript", "-e", applescript])
		elif sys.platform == "win32":
			os.startfile(path)
		elif sys.platform.startswith("linux"):
			subprocess.call(["xdg-open", path])
	except Exception as e:
		print(f"⚠️ Could not reopen Excel file:\n{e}")
