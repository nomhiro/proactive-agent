// Functions の実行とデプロイ用、確認用のキューと結果の置き場。共有キーは使わない
param location string
param tags object
@minLength(3)
param resourceToken string
param deployerPrincipalId string

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'st${resourceToken}'
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowSharedKeyAccess: false
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blob 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [
  for name in ['app-package', 'probe-results']: {
    parent: blob
    name: name
  }
]

resource queueService 'Microsoft.Storage/storageAccounts/queueServices@2023-05-01' = {
  parent: account
  name: 'default'
}

resource probeQueue 'Microsoft.Storage/storageAccounts/queueServices/queues@2023-05-01' = {
  parent: queueService
  name: 'probe'
}

// デプロイする人: キューへの投入（Storage Queue Data Message Sender）と結果の読み取り（Storage Blob Data Reader）
var deployerRoles = [
  'c6a89b2d-59bc-44d0-9896-0f6e12d7b80a'
  '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1'
]

resource deployerAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in deployerRoles: {
    scope: account
    name: guid(account.id, deployerPrincipalId, roleId)
    properties: {
      principalId: deployerPrincipalId
      principalType: 'User'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
    }
  }
]

output name string = account.name
output deploymentContainerUrl string = '${account.properties.primaryEndpoints.blob}app-package'
