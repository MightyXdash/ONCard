#ifndef AppName
  #define AppName "ONCards"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "MightyXdash"
#endif
#ifndef SourceRoot
  #define SourceRoot ".."
#endif
#ifndef BuildOutput
  #define BuildOutput "..\build\nuitka\main.dist"
#endif
#ifndef InstallerOutput
  #define InstallerOutput "..\build\installer"
#endif

[Setup]
AppId={{84E3C4AF-30A8-473A-8EFA-38BE657F8C1E}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\ONCards
DefaultGroupName=ONCards
DisableDirPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
OutputDir={#InstallerOutput}
OutputBaseFilename=ONCards-Setup-{#AppVersion}
UninstallDisplayIcon={app}\ONCards.exe

[Files]
Source: "{#BuildOutput}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ONCards"; Filename: "{app}\ONCards.exe"
Name: "{group}\Uninstall ONCards"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ONCards.exe"; Description: "Launch ONCards"; Flags: nowait postinstall skipifsilent
