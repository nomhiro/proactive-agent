// MCP サーバーのトークンの宛先（audience）になる Entra アプリ登録。
// MCP 接続（agentic-identity）はエージェントの ID でこの宛先のトークンを取る
extension microsoftGraphV1

param environmentName string
param resourceToken string

var uniqueName = 'proactive-spike-mcp-${resourceToken}'
var identifierUri = 'api://${tenant().tenantId}/${uniqueName}'

resource app 'Microsoft.Graph/applications@v1.0' = {
  uniqueName: uniqueName
  displayName: 'proactive-agent spike MCP (${environmentName})'
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
