; Windows 安装包（Inno Setup 6）。CI 里由 .github/workflows/build.yml 调用。
; 保持英文界面：Inno 的中文语言包不是默带，缺文件会导致编译失败。

[Setup]
AppName=Drag Drop Transcriber
AppVersion=1.0.0
AppPublisher=local
DefaultDirName={autopf}\Transcriber
DefaultGroupName=Transcriber
DisableProgramGroupPage=yes
OutputBaseFilename=Transcriber-win-x64-Setup
OutputDir=..\dist
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
UninstallDisplayIcon={app}\Transcriber.exe

[Messages]
BeveledLabel=webm / mp4 / mp3 -> Word

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\Transcriber\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Transcriber"; Filename: "{app}\Transcriber.exe"
Name: "{autodesktop}\Transcriber"; Filename: "{app}\Transcriber.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Transcriber.exe"; Description: "Launch Transcriber"; Flags: nowait postinstall skipifsilent
