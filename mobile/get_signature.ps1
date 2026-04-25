$hex = (& "C:\Program Files\Android\Android Studio\jbr\bin\keytool.exe" -list -v -keystore "$env:USERPROFILE\.android\debug.keystore" -alias androiddebugkey -storepass android -keypass android | Select-String "SHA256").ToString().Split("SHA256:")[1].Trim()
$bytes = ($hex -split ":") | ForEach-Object { [Convert]::ToByte($_, 16) }
[Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+","-").Replace("/","_")
