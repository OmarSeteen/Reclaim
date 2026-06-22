"""Tiny translation layer. English text is the lookup key.

Strings in the UI are written in plain English and passed through `t()`. That
English string IS the key, so a missing translation degrades to showing English
rather than crashing or printing a raw token — new strings are safe before
they're translated. `t()` returns a template; callers add dynamic values with
`.format(...)`, so the placeholders (e.g. "{size}") survive translation.

Arabic is right-to-left (see `is_rtl`); the UI layer mirrors the layout when an
RTL language is active. Adding a language = one more entry in TRANSLATIONS.
"""

# Display names for the language picker, keyed by the code stored in settings.
LANGUAGES = {"en": "English", "ar": "العربية"}

# English -> Arabic. Anything absent falls back to the English key automatically.
_AR = {
    # Header / chrome
    "Map your drive, then reclaim space safely.": "حلّل قرصك، ثم استعد المساحة بأمان.",
    "History": "السجل",
    "Settings": "الإعدادات",
    "Cancel": "إلغاء",
    "Restart as admin": "إعادة التشغيل كمسؤول",
    "⚠  Not admin — Update / Delivery Optimization / WER may be partly skipped.":
        "⚠  لست مسؤولاً — قد يُتخطّى جزء من تحديثات ويندوز / تحسين التسليم / تقارير الأخطاء.",
    "Activity log": "سجل النشاط",
    "Log": "السجل",
    "☕  Buy me a coffee": "☕  ادعمني بقهوة",
    "Disk usage unavailable": "تعذّر قراءة استخدام القرص",
    "{pct}% used": "مستخدم {pct}%",
    "free": "متاح",
    "total": "الإجمالي",

    # Tabs
    "Cleanup": "حذف الملفات",
    "Disk Analyzer": "محلّل القرص",
    "Duplicates": "الملفات المكرّرة",
    "Old Downloads": "التنزيلات القديمة",
    "Claim old files": "استرجاع الملفات القديمة",
    "Folder tree": "شجرة المجلدات",
    "Treemap": "الخريطة الشجرية",
    "Largest files": "أكبر الملفات",
    "By file type": "حسب النوع",

    # Buttons
    "Select all": "تحديد الكل",
    "Deselect all": "إلغاء تحديد الكل",
    "Analyze": "تحليل",
    "Preview": "معاينة",
    "Recommended clean": "تنظيف موصى به",
    "Clean selected": "تنظيف المحدد",
    "Browse": "استعراض",
    "Scan": "فحص",
    "Find duplicates": "بحث عن المكرّرات",
    "Find old files": "بحث عن الملفات القديمة",
    "Select all but one per group": "تحديد الكل عدا نسخة لكل مجموعة",
    "Clear selection": "مسح التحديد",
    "Move selected to Recycle Bin": "نقل المحدد إلى سلة المحذوفات",
    "Move selected to another drive…": "نقل المحدد إلى قرص آخر…",
    "↑ Up": "↑ للأعلى",
    "Close": "إغلاق",
    "Add…": "إضافة…",
    "Remove": "إزالة",

    # Field labels
    "Folder:": "المجلد:",
    "Drive:": "محرك الأقراص:",
    "Min size": "أدنى حجم",
    "MB": "ميغابايت",
    "Older than": "أقدم من",
    "months": "شهراً",

    # Column headings
    "Folder / file": "مجلد / ملف",
    "Size": "الحجم",
    "% of parent": "% من الأصل",
    "Group / file": "مجموعة / ملف",
    "Path": "المسار",
    "Age": "العمر",
    "File": "ملف",
    "Category / path": "الفئة / المسار",
    "Type": "النوع",
    "Total size": "الحجم الإجمالي",

    # Status lines (static)
    "Click Analyze to see reclaimable space": "اضغط «تحليل» لعرض المساحة القابلة للاسترجاع",
    "Calculating reclaimable space…": "جارٍ حساب المساحة القابلة للاسترجاع…",
    "Scan a drive to map every folder and file.": "افحص قرصاً لتعيين كل مجلد وملف.",
    "Scan a folder to see its treemap.": "افحص مجلداً لعرض خريطته الشجرية.",
    "Finds byte-identical copies. Keeps one, sends the rest to the Recycle Bin (undoable).":
        "يجد النسخ المتطابقة تماماً، يُبقي نسخة واحدة ويرسل الباقي إلى سلة المحذوفات (قابل للتراجع).",
    "Lists files you haven't touched in a while. Relocate big files to another drive, "
    "or send them to the Recycle Bin (undoable).":
        "يسرد الملفات التي لم تستخدمها منذ مدة. انقل الكبيرة منها إلى قرص آخر، "
        "أو أرسلها إلى سلة المحذوفات (قابل للتراجع).",

    # Status lines (templated — placeholders kept verbatim)
    "Total reclaimable: {v}": "إجمالي القابل للاسترجاع: {v}",
    "Freed {v} this run": "تم تحرير {v} في هذه الجولة",
    "{drive}  —  {free} free of {total} ({pct}% used)":
        "{drive}  —  {free} متاح من أصل {total} (مستخدم {pct}%)",

    # Messageboxes — titles
    "Nothing selected": "لا يوجد تحديد",
    "Invalid folder": "مجلد غير صالح",
    "Invalid value": "قيمة غير صالحة",
    "Invalid destination": "وجهة غير صالحة",
    "Administrator recommended": "يُنصح بصلاحيات المسؤول",
    "Confirm cleanup": "تأكيد التنظيف",
    "Done": "تم",
    "OK": "موافق",
    "Move to Recycle Bin": "النقل إلى سلة المحذوفات",
    "Move files": "نقل الملفات",
    "Same drive": "القرص نفسه",
    "Restart needed": "يلزم إعادة التشغيل",

    # Messageboxes — bodies
    "Tick at least one category.": "حدّد فئة واحدة على الأقل.",
    "Select files first.": "حدّد الملفات أولاً.",
    "Select the duplicate files to remove first.": "حدّد الملفات المكرّرة المراد حذفها أولاً.",
    "Min size must be a whole number.": "يجب أن يكون أدنى حجم عدداً صحيحاً.",
    "Days must be a whole number.": "يجب أن تكون الأيام عدداً صحيحاً.",
    "Not a folder:\n{path}": "ليس مجلداً:\n{path}",
    "Some selected items need admin to clear fully.\nLocked files are skipped.\n\nContinue anyway?":
        "تحتاج بعض العناصر المحددة إلى صلاحيات المسؤول لمسحها بالكامل.\n"
        "يتم تخطّي الملفات المقفلة.\n\nهل تريد المتابعة؟",
    "Permanently delete the contents of:\n\n{names}\n\n"
    "Files in use are skipped automatically.\n\nProceed?":
        "حذف محتويات ما يلي نهائياً:\n\n{names}\n\n"
        "يتم تخطّي الملفات قيد الاستخدام تلقائياً.\n\nهل تريد المتابعة؟",
    "Cleanup complete.\nFreed approximately {v}.": "اكتمل التنظيف.\nتم تحرير ما يقارب {v}.",
    "Move {n} duplicate file(s) to the Recycle Bin?\n\n"
    "They stay recoverable there until you empty it.":
        "نقل {n} ملفاً مكرراً إلى سلة المحذوفات؟\n\nتبقى قابلة للاستعادة حتى تُفرّغ السلة.",
    "Move {n} file(s) to the Recycle Bin?\n\n"
    "They stay recoverable there until you empty it.":
        "نقل {n} ملفاً إلى سلة المحذوفات؟\n\nتبقى قابلة للاستعادة حتى تُفرّغ السلة.",
    "Move {n} file(s) to:\n{dest}\n\nEach file is copied, then removed from its "
    "current location. Anything in use is skipped (and left where it is).":
        "نقل {n} ملفاً إلى:\n{dest}\n\nيُنسخ كل ملف ثم يُحذف من موقعه الحالي. "
        "ويُتخطّى أي ملف قيد الاستخدام (ويبقى مكانه).",
    "The destination is on the same drive ({drive}).\n"
    "Moving here won't free space on that drive.\n\nMove anyway?":
        "الوجهة على القرص نفسه ({drive}).\n"
        "النقل إلى هنا لن يحرّر مساحة على ذلك القرص.\n\nهل تريد المتابعة؟",
    "Restart the app to apply the new language.": "أعد تشغيل التطبيق لتطبيق اللغة الجديدة.",

    # Dialogs
    "Choose a destination folder (ideally on another drive)":
        "اختر مجلد وجهة (يُفضّل على قرص آخر)",
    "Preview — what would be removed": "معاينة — ما الذي سيُحذف",
    "Nothing is deleted here. This is exactly what 'Clean selected' would remove.":
        "لا يُحذف شيء هنا. هذا تماماً ما سيحذفه «تنظيف المحدد».",
    "(nothing found)": "(لا شيء)",
    "Cleanup history": "سجل التنظيف",
    "Clear history": "مسح السجل",
    "Language": "اللغة",
    "Custom folders to clean": "مجلدات مخصّصة للتنظيف",
    "Their contents are cleared like any cache. Added as the 'Custom folders' cleanup category.":
        "تُمسح محتوياتها كأي ذاكرة مؤقتة. تُضاف كفئة «مجلدات مخصّصة».",
    "Folders to exclude from scans": "مجلدات تُستثنى من الفحص",
    "Skipped by the Disk Analyzer, Duplicates and Old-files scans (and everything under them).":
        "تُتخطّى في فحوص محلّل القرص والمكرّرات والملفات القديمة (وكل ما بداخلها).",

    # Cleaner category labels
    "Temporary files": "الملفات المؤقتة",
    "Recycle Bin": "سلة المحذوفات",
    "Browser caches": "ذاكرة المتصفحات المؤقتة",
    "App caches": "ذاكرة التطبيقات المؤقتة",
    "Developer caches": "ذاكرة أدوات المطورين",
    "Windows Update cache": "ذاكرة تحديث ويندوز",
    "Delivery Optimization files": "ملفات تحسين التسليم",
    "Error reporting dumps": "تقارير أخطاء ويندوز",
    "System crash dumps": "تفريغات أعطال النظام",
    "Windows servicing logs": "سجلات صيانة الويندوز",
    "Thumbnail cache": "ذاكرة الصور المصغّرة",
    "Custom folders": "مجلدات مخصّصة",
    "Windows component store cleanup": "تنظيف مخزن مكوّنات ويندوز",
    "Hibernation file": "ملف الإسبات",
    "Previous Windows installation": "ملفات تثبيت ويندوز السابق",

    # Cleaner descriptions
    "User + Windows temp folders. Always safe to clear.":
        "مجلدات المؤقتات للمستخدم وويندوز. آمنة دائماً للمسح.",
    "Permanently empties the Recycle Bin.": "تُفرّغ سلة المحذوفات نهائياً.",
    "Chrome, Edge, Brave, Vivaldi, Opera & Firefox caches (all profiles). Logins kept.":
        "ذاكرة Chrome وEdge وBrave وVivaldi وOpera وFirefox (لكل الملفات الشخصية). تبقى تسجيلات الدخول.",
    "Discord, Spotify, Teams, Slack, Zoom & WhatsApp caches.":
        "ذاكرة Discord وSpotify وTeams وSlack وZoom وWhatsApp المؤقتة.",
    "npm, yarn, pnpm, pip, Gradle, Maven, NuGet, Cargo, Go & editor caches. Rebuilt on next build.":
        "ذاكرة npm وyarn وpnpm وpip وGradle وMaven وNuGet وCargo وGo والمحررات. يُعاد بناؤها لاحقاً.",
    "Old downloaded update files. Needs admin to clear fully.":
        "ملفات تحديث قديمة مُنزّلة. تحتاج صلاحيات مسؤول للمسح الكامل.",
    "Cached update-sharing data. Rebuilds automatically. Needs admin.":
        "بيانات مشاركة التحديثات المؤقتة. يُعاد بناؤها تلقائياً. تحتاج صلاحيات مسؤول.",
    "Windows Error Reporting archives & crash dumps.":
        "أرشيفات تقارير أخطاء ويندوز وتفريغات الأعطال.",
    "Kernel memory dumps & minidumps from past crashes. Needs admin.":
        "تفريغات ذاكرة النواة والتفريغات المصغّرة من أعطال سابقة. تحتاج صلاحيات مسؤول.",
    "CBS / DISM / setup logs. Regenerated as needed. Needs admin.":
        "سجلات CBS / DISM / الإعداد. يُعاد إنشاؤها عند الحاجة. تحتاج صلاحيات مسؤول.",
    "Explorer thumbnail/icon cache. Rebuilds automatically.":
        "ذاكرة الصور المصغّرة/الأيقونات في المستكشف. يُعاد بناؤها تلقائياً.",
    "Folders you've added under Settings. Their contents are cleared.":
        "مجلدات أضفتها من الإعدادات. تُمسح محتوياتها.",
    "Removes superseded update components via DISM. Needs admin; can take a while.":
        "يزيل مكوّنات التحديث المتجاوَزة عبر DISM. يحتاج صلاحيات مسؤول؛ قد يستغرق وقتاً.",
    "Deletes hiberfil.sys by turning hibernation off (also disables Fast Startup). Needs admin.":
        "يحذف hiberfil.sys بإيقاف الإسبات (يُعطّل أيضاً بدء التشغيل السريع). يحتاج صلاحيات مسؤول.",
    "Removes C:\\Windows.old left by a feature update. Needs admin; cannot be undone.":
        "يزيل C:\\Windows.old المتبقّي من تحديث ميزات. يحتاج صلاحيات مسؤول؛ لا يمكن التراجع.",

    # PySide6 UI: header control + live status/progress lines (templated)
    "Light mode": "الوضع الفاتح",
    "Dark mode": "الوضع الداكن",
    "Working…": "جارٍ العمل…",
    "Nothing removed — the selected files weren't found "
    "(in use, protected, or already gone).":
        "لم يُحذف شيء — لم يتم العثور على الملفات المحددة "
        "(قيد الاستخدام أو محمية أو مُزالة بالفعل).",
    "Cancelled.": "أُلغي.",
    "Cancelling… (finishing the current step)": "جارٍ الإلغاء… (إنهاء الخطوة الحالية)",
    "Analyzing… (read-only)": "جارٍ التحليل… (قراءة فقط)",
    "Starting cleanup…": "بدء التنظيف…",
    "Scanning for duplicates…": "البحث عن المكرّرات…",
    "Finding old files…": "البحث عن الملفات القديمة…",
    "Scanning {p}…": "جارٍ فحص {p}…",
    "Scanned {n} files…": "تم فحص {n} ملف…",
    "Scanned {n} files · {sz} total.": "تم فحص {n} ملف · الإجمالي {sz}.",
    "Hashing… {n} candidate files": "حساب البصمات… {n} ملف مرشّح",
    "{n} duplicate groups · {sz} reclaimable.": "{n} مجموعة مكرّرة · {sz} قابلة للاسترجاع.",
    "{n} copies · {sz} reclaimable": "{n} نسخة · {sz} قابلة للاسترجاع",
    "{n} files older than {m} months · {sz} total.":
        "{n} ملف أقدم من {m} شهراً · الإجمالي {sz}.",
    "Moved {n} duplicates to Recycle Bin · freed {sz}.":
        "نُقل {n} ملف مكرر إلى سلة المحذوفات · تم تحرير {sz}.",
    "Moved {n} files to Recycle Bin · freed {sz}.":
        "نُقل {n} ملف إلى سلة المحذوفات · تم تحرير {sz}.",
    "Moved {n} files · freed {sz}.": "نُقل {n} ملف · تم تحرير {sz}.",
    "Moved {n} of {total} files to {dest} · freed {sz} on the source drive.":
        "نُقل {n} من {total} ملف إلى {dest} · تم تحرير {sz} على القرص المصدر.",

    # Empty-state / placeholder text on the Duplicates and Old-files tabs
    "Scan a folder to find duplicate files.": "افحص مجلداً للعثور على الملفات المكرّرة.",
    "No duplicates found.": "لا توجد ملفات مكرّرة.",
    "Find files you haven't used in a while.": "ابحث عن ملفات لم تستخدمها منذ مدة.",
    "No files found.": "لا توجد ملفات.",

    # Duplicates tab — result filters
    "Filter:": "تصفية:",
    "Filter by name or path…": "تصفية بالاسم أو المسار…",
    "All types": "كل الأنواع",
    "No duplicates match the filter.": "لا توجد مكرّرات مطابقة للتصفية.",
    "Showing {shown} of {total} groups · {sz} reclaimable.":
        "عرض {shown} من {total} مجموعة · {sz} قابلة للاسترجاع.",
}

_TRANSLATIONS = {"ar": _AR}
_current = "en"


def set_language(lang):
    """Set the active language code; anything unknown falls back to English."""
    global _current
    _current = lang if lang in LANGUAGES else "en"


def get_language():
    return _current


def is_rtl():
    """True for right-to-left languages (currently just Arabic)."""
    return _current == "ar"


def t(text):
    """Translate `text` for the active language, or return it unchanged.

    English passes straight through; for other languages a missing entry returns
    the English key, so the UI is never broken by an untranslated string.
    """
    if _current == "en":
        return text
    return _TRANSLATIONS.get(_current, {}).get(text, text)
