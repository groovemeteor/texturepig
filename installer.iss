; installer.iss
; Inno Setup script for Texture Pig.
;
; Packages the PyInstaller onedir build (dist\TexturePig\) into a single,
; ordinary Windows installer: Start Menu shortcut, optional desktop icon,
; a proper uninstaller in "Apps & Features", and one distributable .exe
; (Inno Setup LZMA-compresses the payload for the download, but installs it
; uncompressed on disk -- so the fast onedir startup is unaffected).
;
; Build order:
;   1. build.bat  (or: pyinstaller --clean -y TexturePig.spec)
;      -> produces dist\TexturePig\TexturePig.exe + supporting files
;   2. ISCC.exe installer.iss
;      -> produces installer_output\TexturePigSetup-<version>.exe
;
; Requires Inno Setup 6 (https://jrsoftware.org/isinfo.php).

#define MyAppName "Texture Pig"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "Robin Grotenfelt"
#define MyAppExeName "TexturePig.exe"
#define MyAppURL "https://github.com/groovemeteor/texture_pig"
#define MyBuildDir "dist\TexturePig"

[Setup]
AppId={{B6C6E9B9-6E0B-4B7B-9C8C-3E7B7B5C9F41}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Per-user install by default (no admin prompt) -- installs to the user's
; local AppData\Programs instead of Program Files. Flip PrivilegesRequired
; to "admin" + DefaultDirName back to {autopf} if a machine-wide install
; (shared across Windows accounts) is preferred instead.
PrivilegesRequired=lowest
UsePreviousAppDir=yes
OutputDir=installer_output
OutputBaseFilename=TexturePigSetup-{#MyAppVersion}
SetupIconFile=ui\icons\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; No LICENSE file in the repo yet -- add one and uncomment this to show a
; license-acceptance page in the wizard:
; LicenseFile=LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; Everything PyInstaller collected into dist\TexturePig\, recursively.
Source: "{#MyBuildDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; A file association (e.g. double-click a saved graph to open it in Texture
; Pig) isn't wired up here: the app never reads sys.argv at startup, so it
; wouldn't actually load whatever file Windows passed it. Add argv handling
; in ui/qt_editor.py's run()/load_graph_async() first, then add a [Registry]
; section associating the extension with "{app}\{#MyAppExeName}" "%1".

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Onedir builds leave behind __pycache__/log files some runs create next to
; the install; make sure a clean uninstall removes the whole folder.
Type: filesandordirs; Name: "{app}"
