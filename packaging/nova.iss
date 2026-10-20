; Inno Setup script — the NOVA setup program for Windows. Built by packaging\build_windows.ps1.
; Installs for the current user only (no administrator rights needed), adds a Start menu shortcut and an uninstaller.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\NOVA"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{6C0B6F0E-3A0B-4C4E-9E4F-2B7A1D5E6A31}
AppName=NOVA
AppVersion={#AppVersion}
AppPublisher=Martin
AppPublisherURL=https://github.com/Martin-gif-maker/NOVA
DefaultDirName={localappdata}\Programs\NOVA
DefaultGroupName=NOVA
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=NOVA-{#AppVersion}-setup
SetupIconFile=..\nova.ico
UninstallDisplayIcon={app}\NOVA.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "bulgarian"; MessagesFile: "compiler:Languages\Bulgarian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\NOVA"; Filename: "{app}\NOVA.exe"
Name: "{autodesktop}\NOVA"; Filename: "{app}\NOVA.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\NOVA.exe"; Description: "{cm:LaunchProgram,NOVA}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; what the app wrote for the user (settings, chats, keys) is deliberately left alone: Settings → Privacy → "Delete all my data" removes it
Type: filesandordirs; Name: "{app}"

[Registry]
; the "start with Windows" entry and the nova:// link handler are removed with the app
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "NOVA"; Flags: dontcreatekey uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\nova"; Flags: dontcreatekey uninsdeletekey
