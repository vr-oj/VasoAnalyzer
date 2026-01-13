#define MyAppName "VasoAnalyzer"
#define MyAppVersion "2.3.0"
#define MyAppPublisher "Tykocki Lab"
#define MyAppExeName "VasoAnalyzer.exe"
#define MyAppId "{{C7E28CDA-3B4A-4C42-9DD4-84B0437D0B5E}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=installer\windows\output
OutputBaseFilename=VasoAnalyzer-Setup
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
ChangesAssociations=yes
SetupIconFile=..\..\src\vasoanalyzer\VasoAnalyzerIcon.ico

[Files]
Source: "..\..\dist\VasoAnalyzer\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\assets\icons\VasoDocument.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\VasoAnalyzer"; Filename: "{app}\{#MyAppExeName}"
Name: "{commondesktop}\VasoAnalyzer"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Registry]
Root: HKCR; Subkey: ".vaso"; ValueType: string; ValueName: ""; ValueData: "VasoAnalyzer.Project"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "VasoAnalyzer.Project"; ValueType: string; ValueName: ""; ValueData: "VasoAnalyzer Project"; Flags: uninsdeletekey
Root: HKCR; Subkey: "VasoAnalyzer.Project\\DefaultIcon"; ValueType: string; ValueData: "{app}\VasoDocument.ico,0"; Flags: uninsdeletevalue
Root: HKCR; Subkey: "VasoAnalyzer.Project\\shell\\open\\command"; ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch VasoAnalyzer"; Flags: nowait postinstall skipifsilent
