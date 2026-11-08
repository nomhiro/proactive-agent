// Cosmos DB for NoSQL（サーバーレス）。キーでの接続は無効にし、Entra ID のデータ権限だけで使う
param location string
param tags object
param resourceToken string

@description('組み込みの Data Contributor を付ける object ID（Functions の ID、デプロイする人）')
param dataContributorPrincipalIds array

var databaseName = 'proactive'
var vehicleContainers = [
  'artifacts'
  'change_events'
  'test_runs'
  'watches'
  'messages'
  'proposals'
  'agent_mail'
  'notifications'
  'agent_runs'
  'schedules'
  'team_settings'
  'investigations'
  'system'
]

resource account 'Microsoft.DocumentDB/databaseAccounts@2024-11-15' = {
  name: 'cosmos-${resourceToken}'
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    capabilities: [{ name: 'EnableServerless' }]
    disableLocalAuth: true
    consistencyPolicy: { defaultConsistencyLevel: 'Session' }
    locations: [{ locationName: location, failoverPriority: 0, isZoneRedundant: false }]
    publicNetworkAccess: 'Enabled'
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-11-15' = {
  parent: account
  name: databaseName
  properties: { resource: { id: databaseName } }
}

resource containers 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = [
  for name in vehicleContainers: {
    parent: database
    name: name
    properties: {
      resource: {
        id: name
        partitionKey: { paths: ['/vehicle_id'], kind: 'Hash' }
      }
    }
  }
]

resource leases 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-11-15' = {
  parent: database
  name: 'leases'
  properties: {
    resource: {
      id: 'leases'
      partitionKey: { paths: ['/id'], kind: 'Hash' }
    }
  }
}

// 00000000-0000-0000-0000-000000000002 = Cosmos DB Built-in Data Contributor
resource dataContributors 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-11-15' = [
  for principalId in dataContributorPrincipalIds: {
    parent: account
    name: guid(account.id, principalId, 'data-contributor')
    properties: {
      principalId: principalId
      roleDefinitionId: '${account.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
      scope: account.id
    }
  }
]

output endpoint string = account.properties.documentEndpoint
output databaseName string = databaseName
output accountName string = account.name
