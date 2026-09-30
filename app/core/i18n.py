"""UI language. Follows Windows unless Settings picks English or Khmer."""
from PySide6.QtCore import QLocale

_LANGUAGE = "en"

_KM = {
    "Name": "ឈ្មោះ",
    "Variant": "ប្រភេទ",
    "Hoster": "ប្រភព",
    "Status": "ស្ថានភាព",
    "Progress": "វឌ្ឍនភាព",
    "Uploader": "អ្នកបង្ហោះ",
    "ID": "លេខសម្គាល់",
    "Size": "ទំហំ",
    "Duration": "រយៈពេល",
    "Speed": "ល្បឿន",
    "ETA": "ពេលនៅសល់",
    "Save to": "រក្សាទុកនៅ",
    "Download from": "ទាញយកពី",
    "Added": "បានបន្ថែម",
    "Queued": "ក្នុងជួរ",
    "Downloading": "កំពុងទាញយក",
    "Done": "រួចរាល់",
    "Failed": "បរាជ័យ",
    "Cancelled": "បានបោះបង់",
    "Video": "វីដេអូ",
    "Audio": "សំឡេង",
    "Music": "តន្ត្រី",
    "Image": "រូបភាព",
    "Document": "ឯកសារ",
    "Download": "ទាញយក",
    "Grabber": "ចាប់តំណ",
    "No downloads": "គ្មានការទាញយក",
    "No links": "គ្មានតំណ",
    "No items": "គ្មានធាតុ",
    "Add New Links": "បន្ថែមតំណថ្មី",
    "Add to downloads": "បន្ថែមទៅការទាញយក",
    "Start all Downloads": "ទាញយកទាំងអស់",
    "Start all downloads": "ទាញយកទាំងអស់",
    "Continue Downloads": "បន្តទាញយក",
    "Continue login": "បន្តការចូល",
    "Cancel": "បោះបង់",
    "Extract": "ស្រង់",
    "File": "ឯកសារ",
    "Edit": "កែសម្រួល",
    "View": "មើល",
    "Tools": "ឧបករណ៍",
    "Help": "ជំនួយ",
    "Extract list": "ស្រង់បញ្ជី",
    "Cancel job": "បោះបង់ការងារ",
    "Open download folder": "បើកថតទាញយក",
    "Export list…": "នាំចេញបញ្ជី…",
    "Import list…": "នាំចូលបញ្ជី…",
    "Retry failed items": "ព្យាយាមធាតុបរាជ័យម្តងទៀត",
    "Settings…": "ការកំណត់…",
    "Exit": "ចេញ",
    "Select all": "ជ្រើសទាំងអស់",
    "Invert checks": "បញ្ច្រាសការគូស",
    "Copy URL": "ចម្លង URL",
    "Copy caption": "ចម្លងចំណងជើង",
    "Open in browser": "បើកក្នុងកម្មវិធីរុករក",
    "Remove selected": "លុបអ្វីដែលបានជ្រើស",
    "Remove all": "លុបទាំងអស់",
    "Remove all from list": "លុបទាំងអស់ពីបញ្ជី",
    "Move up": "ផ្លាស់ទីឡើង",
    "Move down": "ផ្លាស់ទីចុះ",
    "Show log": "បង្ហាញកំណត់ហេតុ",
    "Show status bar": "បង្ហាញរបារស្ថានភាព",
    "Show overview": "បង្ហាញទិដ្ឋភាពសង្ខេប",
    "Package or Link Properties": "លក្ខណៈសម្បត្តិកញ្ចប់ ឬតំណ",
    "Show sidebar": "បង្ហាញរបារចំហៀង",
    "Show bottom tools": "បង្ហាញឧបករណ៍ខាងក្រោម",
    "Dark theme": "រចនាប័ទ្មងងឹត",
    "Lock column layout": "ចាក់សោប្លង់ជួរឈរ",
    "Reset columns": "កំណត់ជួរឈរឡើងវិញ",
    "Link Grabber": "ចាប់តំណ",
    "Show grabber monitor": "បង្ហាញការតាមដាន",
    "Check for tool updates": "ពិនិត្យបច្ចុប្បន្នភាពឧបករណ៍",
    "Check for app updates": "ពិនិត្យបច្ចុប្បន្នភាពកម្មវិធី",
    "Open app data folder": "បើកថតទិន្នន័យកម្មវិធី",
    "Supported sites": "គេហទំព័រដែលគាំទ្រ",
    "Send feedback…": "ផ្ញើមតិ…",
    "About": "អំពី",
    "General": "ទូទៅ",
    "Notifications": "ការជូនដំណឹង",
    "Appearance": "រូបរាង",
    "Cookies": "ខូគី",
    "Theme style": "រចនាប័ទ្ម",
    "Primary color": "ពណ៌ចម្បង",
    "Language": "ភាសា",
    "Follow system": "តាមប្រព័ន្ធ",
    "Extra fonts": "ពុម្ពអក្សរបន្ថែម",
    "Log": "កំណត់ហេតុ",
    "Export log…": "នាំចេញកំណត់ហេតុ…",
    "Open logs folder": "បើកថតកំណត់ហេតុ",
    "Open in a new window": "បើកក្នុងបង្អួចថ្មី",
    "Dock in the main window": "ដាក់ក្នុងបង្អួចចម្បង",
    "Close log": "បិទកំណត់ហេតុ",
    "Idle": "ទំនេរ",
    "Grabber on": "ចាប់តំណបើក",
    "Grabber off": "ចាប់តំណបិទ",
    "Working…": "កំពុងធ្វើ…",
    "Extracting…": "កំពុងស្រង់…",
    "Link Grabber…": "កំពុងចាប់តំណ…",
    "downloading": "កំពុងទាញយក",
    "{n} listed": "{n} បានរាយ",
    "{n} ready": "{n} រួចរាល់",
    "Fit columns to content": "សមជួរឈរតាមខ្លឹមសារ",
    "Horizontal scrollbar": "របាររំកិលផ្ដេក",
    "Paste Links": "បិទភ្ជាប់តំណ",
    "Paste links…": "បិទភ្ជាប់តំណ…",
    "Add links from the clipboard": "បន្ថែមតំណពីក្ដារតម្បៀតខ្ទាស់",
    "Add at top": "បន្ថែមនៅខាងលើ",
    "Auto confirm": "បញ្ជាក់ស្វ័យប្រវត្តិ",
    "Autostart Download": "ទាញយកស្វ័យប្រវត្តិ",
    "Sort by Hoster": "តម្រៀបតាមប្រភព",
    "Other": "ផ្សេងទៀត",
    "Expand all packages": "ពង្រីកកញ្ចប់ទាំងអស់",
    "Collapse all packages": "បង្រួមកញ្ចប់ទាំងអស់",
    "Clean Up...": "សម្អាត...",
    "Delete selected links": "លុបតំណដែលបានជ្រើស",
    "Delete all links": "លុបតំណទាំងអស់",
    "Overview Panel visible": "បង្ហាញផ្ទាំងទិដ្ឋភាពសង្ខេប",
    "Sidebar visible": "បង្ហាញរបារចំហៀង",
    "Customize this Bottom Panel": "កែបន្ទះខាងក្រោមនេះ",
    "Max chunks per download": "ចំនួនផ្នែកអតិបរមាក្នុងមួយការទាញយក",
    "Max simultaneous downloads": "ការទាញយកដំណាលគ្នាអតិបរមា",
    "Speed limit": "កំណត់ល្បឿន",
    "Start checked only": "ទាញយកតែអ្វីដែលបានគូស",
    "Add additional variants": "បន្ថែមប្រភេទបន្ថែម",
    "Download Overview": "ទិដ្ឋភាពទាញយក",
    "Grabber Overview": "ទិដ្ឋភាពចាប់តំណ",
    "Overview": "ទិដ្ឋភាពសង្ខេប",
    "Links": "តំណ",
    "Left": "នៅសល់",
    "Checked": "បានគូស",
    "Known": "ស្គាល់",
    "Unknown": "មិនស្គាល់",
    "File Properties": "លក្ខណៈសម្បត្តិឯកសារ",
    "Comment": "មតិយោបល់",
    "Views": "ទិដ្ឋភាព",
    "Host": "ប្រភព",
    "Folder group": "ក្រុមថត",
    "Extracting links": "កំពុងស្រង់តំណ",
    "Looking for links…": "កំពុងរកតំណ…",
    "Waiting for login": "រង់ចាំការចូល",
    "Log in in Chrome, then click Continue login.": "ចូលក្នុង Chrome រួចចុចបន្តការចូល។",
    "Parse Clipboard": "អានក្ដារតម្បៀតខ្ទាស់",
    "Found Link(s)": "តំណដែលរកឃើញ",
    "Duplicate(s)": "ស្ទួន",
    "Link queue": "ជួរតំណ",
    "Grabber list": "បញ្ជីចាប់តំណ",
    "Download queue": "ជួរទាញយក",
    "Properties": "លក្ខណៈសម្បត្តិ",
    "Rename…": "ប្តូរឈ្មោះ…",
    "Set download directory…": "កំណត់ថតទាញយក…",
    "Set comment…": "កំណត់មតិ…",
    "Show properties panel": "បង្ហាញផ្ទាំងលក្ខណៈសម្បត្តិ",
    "Change Variant": "ប្តូរប្រភេទ",
    "Keep this panel open": "រក្សាផ្ទាំងនេះឱ្យបើក",
    "Hide this panel": "លាក់ផ្ទាំងនេះ",
}


def language():
    return _LANGUAGE


def resolved_language(choice):
    """`system` uses the OS locale. Khmer Windows maps to `km`; everything else stays English."""
    picked = str(choice or "system").strip().lower()
    if picked in ("en", "km"):
        return picked
    name = QLocale.system().name().lower()
    if name.startswith("km"):
        return "km"
    return "en"


def apply_language(choice="system"):
    global _LANGUAGE
    _LANGUAGE = resolved_language(choice)
    return _LANGUAGE


def tr(text):
    """Translate a UI string. English source text is returned unchanged."""
    if text is None:
        return text
    source = str(text)
    if not source or _LANGUAGE != "km":
        return source
    if source in _KM:
        return _KM[source]
    plain = source.replace("&", "")
    return _KM.get(plain, source)
