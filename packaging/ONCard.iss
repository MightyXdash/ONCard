#ifndef AppName
  #define AppName "ONCard"
#endif
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppPublisher
  #define AppPublisher "QyrouLabs"
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
DefaultDirName={localappdata}\Programs\ONCard
DefaultGroupName=ONCard
DisableDirPage=yes
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
UsePreviousAppDir=yes
CloseApplications=yes
CloseApplicationsFilter=ONCard.exe
RestartApplications=no
OutputDir={#InstallerOutput}
OutputBaseFilename=ONCard-Installer-{#AppVersion}
UninstallDisplayIcon={app}\ONCard.exe

[Files]
Source: "{#BuildOutput}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\ONCard"; Filename: "{app}\ONCard.exe"
Name: "{group}\Uninstall ONCard"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ONCard.exe"; Description: "Launch ONCard"; Flags: nowait postinstall skipifsilent; Check: ShouldShowLaunchOption
Filename: "{app}\ONCard.exe"; Flags: nowait skipifsilent; Check: ShouldAutoLaunchAfterUpdate

[Code]
function IsUpdateFlow: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if Uppercase(ParamStr(I)) = '/UPDATEFLOW' then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function IsSilentPatchFlow: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
  begin
    if Uppercase(ParamStr(I)) = '/SILENTPATCH' then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

function ShouldShowLaunchOption: Boolean;
begin
  Result := not IsUpdateFlow;
end;

function ShouldAutoLaunchAfterUpdate: Boolean;
begin
  Result := IsUpdateFlow and not IsSilentPatchFlow;
end;
