// Foundry のアカウント、プロジェクト、モデルのデプロイ。キーは無効にし、Entra だけで使う
param location string
param tags object
param resourceToken string
param deployerPrincipalId string
param functionPrincipalId string
param modelName string
param modelVersion string
param modelCapacity int = 50

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: 'aif-${resourceToken}'
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: 'aif-${resourceToken}'
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: modelName
  sku: { name: 'GlobalStandard', capacity: modelCapacity }
  properties: {
    model: { format: 'OpenAI', name: modelName, version: modelVersion }
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: 'proj-spike'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'proactive spike'
    description: 'harness 付きエージェントの確認用（使い捨て）'
  }
  dependsOn: [deployment]
}

// ロールは名前の変更中のため GUID で指定する（ドキュメントの注記どおり）
var foundryUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var foundryProjectManager = 'eadc314b-1a2d-4efa-be10-5d325db5065e'

var assignments = [
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryUser }
  { principalId: deployerPrincipalId, principalType: 'User', roleId: foundryProjectManager }
  { principalId: functionPrincipalId, principalType: 'ServicePrincipal', roleId: foundryUser }
]

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for a in assignments: {
    scope: project
    name: guid(project.id, a.principalId, a.roleId)
    properties: {
      principalId: a.principalId
      principalType: a.principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', a.roleId)
    }
  }
]

output projectEndpoint string = 'https://${account.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output projectId string = project.id
output modelDeployment string = deployment.name
