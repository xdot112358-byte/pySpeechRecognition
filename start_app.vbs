On Error Resume Next
Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
' WScript.ScriptFullName 是获取脚本路径最权威的属性
scriptPath = fso.GetParentFolderName(WScript.ScriptFullName)

If scriptPath = "" Then
    ' 如果上面失败，退而求其次获取工作目录
    scriptPath = WshShell.CurrentDirectory
End If

WshShell.Run scriptPath & "\run.bat", 0, False