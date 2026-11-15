"""Tema visual: colores, tipografía y hoja de estilos (QSS).

QSS es el "CSS de Qt". Tener todos los colores como constantes arriba hace
que cambiar el aspecto de la app sea cuestión de tocar unas pocas líneas.
"""

# Paleta
BG = "#0B1016"          # fondo de la ventana
SURFACE = "#101720"     # panel lateral
CARD = "#161F2A"        # tarjetas de ajustes
BORDER = "#263442"
TEXT = "#EDEDF4"
MUTED = "#8C8CA1"
ACCENT = "#54DCC0"      # violeta
ACCENT_2 = "#8AABFF"    # cian
DANGER = "#FF6B8B"
OK = "#3DDC97"

# Tipografía: en macOS ".AppleSystemUIFont" es San Francisco (SF Pro), la
# fuente del sistema. En otros sistemas Qt usa las alternativas de la lista.
FONT_FAMILY = '".AppleSystemUIFont", "SF Pro Text", "Inter", "Helvetica Neue", "Segoe UI", sans-serif'
MONO_FAMILY = '"SF Mono", "Menlo", "Consolas", monospace'

STYLESHEET = f"""
* {{ font-family: {FONT_FAMILY}; font-size: 13px; color: {TEXT}; outline: 0; }}
QMainWindow, QWidget#root {{ background: {BG}; }}

/* ---------- Cabecera ---------- */
QWidget#header {{ background: {BG}; border-bottom: 1px solid {BORDER}; }}
QLabel#appName {{ font-size: 17px; font-weight: 700; letter-spacing: 0.4px; }}
QLabel#appTag {{ color: {MUTED}; font-size: 12px; }}

/* ---------- Panel lateral ---------- */
QScrollArea#sidebar, QWidget#sidebarBody {{ background: {SURFACE}; border: none; }}
QScrollArea#sidebar {{ border-right: 1px solid {BORDER}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
QLabel#cardTitle {{ font-size: 11px; font-weight: 700; color: {MUTED}; letter-spacing: 1.4px; }}
QLabel#fieldLabel {{ color: {MUTED}; font-size: 12px; }}
QLabel#value {{ font-family: {MONO_FAMILY}; font-size: 12px; color: {TEXT}; }}
QLabel#hint {{ color: {MUTED}; font-size: 11px; }}

/* ---------- Botones ---------- */
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 7px 12px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ACCENT}, stop:1 #278C80);
    border: none; color: white; padding: 9px 22px; font-size: 13px; border-radius: 9px;
}}
QPushButton#primary:hover {{ background: #79E8D0; }}
QPushButton#primary[running="true"] {{ background: {DANGER}; }}

/* ---------- Desplegables y campos ---------- */
QComboBox, QSpinBox, QLineEdit {{
    background: {BG}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 6px 10px; min-height: 18px; selection-background-color: {ACCENT};
}}
QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ border-color: #3A3A4D; }}
QComboBox:focus, QSpinBox:focus, QLineEdit:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;
    selection-background-color: {ACCENT}; padding: 4px;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 0; border: none; }}

/* ---------- Deslizadores ---------- */
QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {ACCENT}, stop:1 {ACCENT_2});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{ background: white; }}

/* ---------- Interruptores (QCheckBox) ---------- */
QCheckBox {{ spacing: 9px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid #3A3A4D; background: {BG};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* ---------- Visor y datos ---------- */
QLabel#viewer {{ background: #07070B; border: 1px solid {BORDER}; border-radius: 14px; color: {MUTED}; }}
QFrame#statChip {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#statValue {{ font-family: {MONO_FAMILY}; font-size: 20px; font-weight: 600; }}
QLabel#statName {{ color: {MUTED}; font-size: 10px; letter-spacing: 1.2px; font-weight: 700; }}
QTableWidget {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px;
    gridline-color: transparent; font-family: {MONO_FAMILY}; font-size: 12px;
}}
QTableWidget::item {{ padding: 3px 8px; border: none; }}
QHeaderView::section {{
    background: {CARD}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
    padding: 7px 8px; font-size: 10px; font-weight: 700; letter-spacing: 1.2px;
}}
QTableCornerButton::section {{ background: {CARD}; border: none; }}
QLabel#status {{ color: {MUTED}; font-size: 12px; }}
QLabel#status[kind="error"] {{ color: {DANGER}; }}

/* ---------- Barras de desplazamiento ---------- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2E2E3D; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""

STYLESHEET += f"""
QTabWidget::pane {{ border: none; background: {SURFACE}; }}
QTabBar::tab {{ background: {SURFACE}; color: {MUTED}; padding: 10px 13px;
    border-bottom: 2px solid {BORDER}; font-weight: 600; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-color: {ACCENT}; }}
QLabel#sectionTitle {{ color: {TEXT}; font-size: 11px; font-weight: 700; padding: 0 2px 7px; }}
QLabel#aimStatus {{ background: #122B2B; color: {ACCENT}; padding: 12px 16px;
    border: 1px solid #254542; border-radius: 10px; font-size: 12px; }}
QPushButton#danger {{ color: {DANGER}; border-color: #633344; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""

STYLESHEET += """
QFrame#captureBanner { background: #30271B; border: 1px solid #75603B; border-radius: 10px; }
QFrame#captureBanner QLabel { color: #F3D9A8; font-size: 12px; }
"""
