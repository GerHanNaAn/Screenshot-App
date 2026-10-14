import copy
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget
from .document import TOOLS
from .storage import defaults, validate


class SettingsDialog(QDialog):
    def __init__(self,settings,apply,parent=None):
        super().__init__(parent)
        self.settings,self.apply = settings,apply
        self.setWindowTitle("Настройки — JoxiLite"); self.resize(560,530)
        layout = QVBoxLayout(self); tabs=QTabWidget(); layout.addWidget(tabs)
        self.capture = {}; self.tools={}
        keys = QWidget(); form=QFormLayout(keys); tabs.addTab(keys,"Горячие клавиши")
        for action,title in (("area","Область"),("window","Окно"),("screen","Экран"),("delayed","С задержкой 3 с")):
            edit=QKeySequenceEdit(); edit.setMaximumSequenceLength(1); form.addRow(title,edit); self.capture[action]=edit
        form.addRow(QLabel("Инструменты — одна буква или цифра без модификаторов"))
        for tool,title in TOOLS.items():
            edit=QKeySequenceEdit(); edit.setMaximumSequenceLength(1); form.addRow(title,edit); self.tools[tool]=edit
        behavior=QWidget(); f=QFormLayout(behavior); tabs.addTab(behavior,"Поведение и история")
        self.escape=QCheckBox("Esc закрывает редактор (иначе отменяет текущий жест)"); f.addRow(self.escape)
        self.confirm=QCheckBox("Предлагать сохранение при закрытии и выходе"); f.addRow(self.confirm)
        self.cursor=QCheckBox("Включать курсор в снимок"); f.addRow(self.cursor)
        self.history=QLineEdit(); row=QHBoxLayout(); row.addWidget(self.history)
        browse=QPushButton("Выбрать…"); browse.clicked.connect(self.browse); row.addWidget(browse); f.addRow("Папка истории",row)
        self.limit=QSpinBox(); self.limit.setRange(1,10000); self.limit.setSuffix(" МБ"); f.addRow("Лимит",self.limit)
        note=QLabel("Снимки хранятся только на этом компьютере.\nУдаляются только старые снимки JoxiLite.\nДля Wayland сочетания подтверждаются в системном диалоге.")
        note.setWordWrap(True); f.addRow(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Save|QDialogButtonBox.StandardButton.Cancel|QDialogButtonBox.StandardButton.RestoreDefaults)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).setText("По умолчанию")
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults).clicked.connect(lambda:self.fill(defaults()))
        layout.addWidget(buttons); self.fill(settings.values)

    def fill(self,values):
        for action,edit in self.capture.items(): edit.setKeySequence(QKeySequence(values["capture_keys"][action]))
        for tool,edit in self.tools.items(): edit.setKeySequence(QKeySequence(values["tool_keys"][tool]))
        self.escape.setChecked(values["close_on_escape"]); self.confirm.setChecked(values["confirm_unsaved"])
        self.cursor.setChecked(values["include_cursor"]); self.history.setText(values["history_dir"]); self.limit.setValue(values["history_limit_mb"])

    def browse(self):
        path=QFileDialog.getExistingDirectory(self,"Папка истории",self.history.text())
        if path: self.history.setText(path)

    def save(self):
        values=copy.deepcopy(self.settings.values)
        values["capture_keys"]={k:v.keySequence().toString(QKeySequence.SequenceFormat.PortableText) for k,v in self.capture.items()}
        values["tool_keys"]={k:v.keySequence().toString(QKeySequence.SequenceFormat.PortableText).upper() for k,v in self.tools.items()}
        values.update(close_on_escape=self.escape.isChecked(),confirm_unsaved=self.confirm.isChecked(),
                      include_cursor=self.cursor.isChecked(),history_dir=self.history.text(),history_limit_mb=self.limit.value())
        try:
            validate(values); self.apply(values)
        except (ValueError,OSError,RuntimeError) as error:
            QMessageBox.warning(self,"Настройки не сохранены",str(error)); return
        self.accept()
