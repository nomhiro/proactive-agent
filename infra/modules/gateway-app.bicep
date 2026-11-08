// 書き込み窓口（Functions の HTTP 関数）のトークンの宛先になる Entra アプリ登録。
// エージェントはこのアプリ宛てのトークンを取って窓口を呼ぶ（キーは使わない）
extension microsoftGraphV1

param environmentName string
param resourceToken string

var uniqueName = 'proactive-gateway-${resourceToken}'
var identifierUri = 'api://${tenant().tenantId}/${uniqueName}'

resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: uniqueName
  displayName: 'proactive-agent gateway (${environmentName})'
  signInAudience: 'AzureADMyOrg'
  identifierUris: [identifierUri]
  api: {
    requestedAccessTokenVersion: 2
  }
}

resource sp 'Microsoft.Graph/servicePrincipals@v1.0' = {
  appId: app.appId
}

output appId string = app.appId
output identifierUri string = identifierUri
