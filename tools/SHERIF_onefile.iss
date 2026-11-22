#ifndef AppExe
  #error AppExe is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
[Setup]
AppId={{D5CE4E29-AD76-480E-A90D-34A987D2DE83}
AppName=SHERIF
AppVersion=1.0.0
DefaultDirName={localappdata}\Programs\SHERIF
DefaultGroupName=SHERIF
PrivilegesRequired=lowest
UsePreviousAppDir=no
OutputDir={#OutputDir}
OutputBaseFilename=SHERIF_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Uninstallable=not IsIsolatedTest
CreateUninstallRegKey=not IsIsolatedTest
[Files]
Source: "{#AppExe}"; DestDir: "{app}"; DestName: "pos.exe"; Flags: ignoreversion
[Icons]
Name: "{group}\SHERIF"; Filename: "{app}\pos.exe"
Name: "{autodesktop}\SHERIF"; Filename: "{app}\pos.exe"
[Code]
function IsIsolatedTest: Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/SHERIF-ISOLATED-TEST') = 0 then Result := True;
end;
